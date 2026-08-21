import calendar as _calendar
import uuid
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.calendar.contract.events import CalendarCreated, CalendarDeleted, CalendarUpdated
from apps.calendar.domain.models import CalendarEvent, CalendarEventRead, format_event_time
from apps.calendar.infra.repository import CalendarEventRepository
from apps.organizations.contract.current import CurrentOrg, CurrentOrgModel
from apps.shared import clock
from apps.shared.events.bus import events
from apps.shared.http import JSON_AND_HTML, delete_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context

router = APIRouter(prefix="/calendar", tags=["calendar"])


async def _get_repo(session: RlsSession, org_id: CurrentOrg) -> CalendarEventRepository:
    return CalendarEventRepository(session, org_id)


CalendarRepo = Annotated[CalendarEventRepository, Depends(_get_repo)]


# ── parsing ────────────────────────────────────────────────────────────────────


def _combine(body: dict, prefix: str) -> str:
    """A datetime from either a single ``<prefix>`` field (JSON) or ``<prefix>_date`` +
    ``<prefix>_time`` (the HTML form's split inputs)."""
    direct = body.get(prefix)
    if direct:
        return str(direct).strip()
    d = str(body.get(f"{prefix}_date", "")).strip()
    t = str(body.get(f"{prefix}_time", "")).strip()
    return f"{d} {t}".strip()


def _org_tz(org: CalendarEvent | object) -> ZoneInfo:
    """The org's zone, falling back to UTC for a missing/blank value."""
    return ZoneInfo(getattr(org, "timezone", None) or "UTC")


def _parse_dt(raw: str, tz: tzinfo = UTC) -> datetime | None:
    """Parse a wall-clock string entered in ``tz`` and return the UTC instant."""
    s = raw.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=tz).astimezone(UTC)
        except ValueError:
            continue
    return None


def _require_times(start_raw: str, end_raw: str, tz: tzinfo = UTC) -> tuple[datetime, datetime]:
    start = _parse_dt(start_raw, tz)
    end = _parse_dt(end_raw, tz)
    if start is None or end is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A valid start and end are required"
        )
    if end <= start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The end time must be after the start time"
        )
    return start, end


# ── view models ─────────────────────────────────────────────────────────────---


def _agenda(events: list[CalendarEvent], tz: tzinfo = UTC) -> list[dict]:
    """Events grouped by day, in chronological order — the list the page renders and tests read.

    Stored UTC instants are rendered in the org's ``tz`` (UTC by default)."""
    groups: list[dict] = []
    for e in events:
        start = e.starts_at.astimezone(tz)
        end = e.ends_at.astimezone(tz)
        label = f"{start:%A}, {start.day} {start:%B} {start.year}"
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "events": []})
        groups[-1]["events"].append(
            {
                "id": str(e.id),
                "title": e.title,
                "time": f"{start:%H:%M} – {end:%H:%M}",
                "location": e.location,
            }
        )
    return groups


def _month_grid(
    events: list[CalendarEvent], ref: date, today: date, tz: tzinfo = UTC
) -> list[list[dict]]:
    """The month's cells, one row per week.

    A multi-day event is placed on every day it spans, not just its start day, and each day marks
    whether it is the event's start or end — which is what lets the grid show the time on the first
    day and a continuation bar on the rest. Spans are computed on the org-local date, so an event
    occupies the days it occupies in the org's timezone.
    """
    local: dict[uuid.UUID, tuple[date, date, str]] = {}
    by_day: dict[date, list[CalendarEvent]] = {}
    for e in events:
        start_local = e.starts_at.astimezone(tz)
        end_local = e.ends_at.astimezone(tz)
        local[e.id] = (start_local.date(), end_local.date(), f"{start_local:%H:%M}")
        span = (end_local.date() - start_local.date()).days
        for offset in range(span + 1):
            by_day.setdefault(start_local.date() + timedelta(days=offset), []).append(e)
    cal = _calendar.Calendar(firstweekday=0)  # Monday-first, matching the mockup

    def _cell_event(ev: CalendarEvent, d: date) -> dict:
        start_date, end_date, start_time = local[ev.id]
        is_start = start_date == d
        is_end = end_date == d
        return {
            "id": str(ev.id),
            "title": ev.title,
            "time": start_time if is_start else "",
            "is_start": is_start,
            "is_end": is_end,
            "multi_day": end_date > start_date,
        }

    return [
        [
            {
                "day": d.day,
                "in_month": d.month == ref.month,
                "is_today": d == today,
                "events": [
                    _cell_event(ev, d)
                    for ev in sorted(by_day.get(d, []), key=lambda x: x.starts_at)
                ],
            }
            for d in week
        ]
        for week in cal.monthdatescalendar(ref.year, ref.month)
    ]


def _ref_month(request: Request) -> date:
    raw = request.query_params.get("month", "")
    parsed = _parse_dt(f"{raw}-01 00:00") if raw else None
    return parsed.date() if parsed else clock.now().date()


def _shift_month(ref: date, months: int) -> str:
    total = ref.year * 12 + (ref.month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ── routes (org-scoped, RLS, member-only) ──────────────────────────────────────


@router.get("", responses=JSON_AND_HTML)
async def list_events(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org: CurrentOrgModel,
) -> Response:
    events = await repo.all()
    if wants_json(request):
        return JSONResponse(
            [CalendarEventRead.model_validate(e).model_dump(mode="json") for e in events]
        )
    tz = _org_tz(org)
    ref = _ref_month(request)
    today = clock.now().astimezone(tz).date()
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        agenda=_agenda(events, tz),
        has_events=bool(events),
        weeks=_month_grid(events, ref, today, tz),
        month_label=f"{ref:%B} {ref.year}",
        prev_month=_shift_month(ref, -1),
        next_month=_shift_month(ref, 1),
    )
    return templates.TemplateResponse(request, "calendar/calendar.html", ctx)


@router.get("/new", response_class=HTMLResponse)
async def new_event_form(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    _org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=None,
        action="calendar",
        is_edit=False,
    )
    return templates.TemplateResponse(request, "calendar/form.html", ctx)


async def _form_error_response(
    request: Request,
    session: RlsSession,
    current_user: CurrentUser,
    org: CurrentOrgModel,
    body: dict,
    *,
    event: CalendarEvent | dict | None,
    action: str,
    error: str,
) -> Response:
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=event,
        action=action,
        # The edit form posts to "calendar/{id}"; the create form to "calendar".
        # Drive the heading off the target, not off ``event`` (set to the rejected
        # body on create so fields repopulate) — else a create error reads "Edit".
        is_edit="/" in action,
        start_date=str(body.get("start_date", "")),
        start_time=str(body.get("start_time", "")),
        end_date=str(body.get("end_date", "")),
        end_time=str(body.get("end_time", "")),
        error=error,
    )
    return templates.TemplateResponse(
        request, "calendar/form.html", ctx, status_code=status.HTTP_422_UNPROCESSABLE_ENTITY
    )


async def _reject(
    request: Request,
    session: RlsSession,
    current_user: CurrentUser,
    org: CurrentOrgModel,
    body: dict,
    *,
    event: CalendarEvent | dict | None,
    action: str,
    error: str,
) -> Response:
    if wants_json(request):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, error)
    return await _form_error_response(
        request, session, current_user, org, body, event=event, action=action, error=error
    )


@router.post("")
async def create_event(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    body = await parse_body(request)

    async def reject(error: str) -> Response:
        return await _reject(
            request, session, current_user, org, body, event=body, action="calendar", error=error
        )

    title = str(body.get("title", "")).strip()
    if not title:
        return await reject("A title is required")
    try:
        start, end = _require_times(_combine(body, "start"), _combine(body, "end"), _org_tz(org))
    except HTTPException as exc:
        return await reject(str(exc.detail))
    event = await repo.add(
        current_user.id,
        title,
        start,
        end,
        location=str(body.get("location", "")),
        description=str(body.get("description", "")),
    )
    await events.emit(
        CalendarCreated(
            user_id=current_user.id, org_id=org_id, entity_id=event.id, entity_name=title
        ),
        session,
    )
    if wants_json(request):
        return JSONResponse(
            CalendarEventRead.model_validate(event).model_dump(mode="json"), status_code=201
        )
    return RedirectResponse(f"/{org.handle}/calendar/{event.id}", status_code=303)


@router.get("/{event_id}", responses=JSON_AND_HTML)
async def view_event(
    request: Request,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org: CurrentOrgModel,
) -> Response:
    event = or_404(await repo.get(event_id))
    if wants_json(request):
        return JSONResponse(CalendarEventRead.model_validate(event).model_dump(mode="json"))
    tz = _org_tz(org)
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=event,
        when=format_event_time(event.starts_at.astimezone(tz), event.ends_at.astimezone(tz)),
    )
    return templates.TemplateResponse(request, "calendar/view.html", ctx)


@router.get("/{event_id}/edit", response_class=HTMLResponse)
async def edit_event_form(
    request: Request,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org: CurrentOrgModel,
) -> Response:
    event = or_404(await repo.get(event_id))
    tz = _org_tz(org)
    start_local, end_local = event.starts_at.astimezone(tz), event.ends_at.astimezone(tz)
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=event,
        action=f"calendar/{event.id}",
        is_edit=True,
        start_date=f"{start_local:%Y-%m-%d}",
        start_time=f"{start_local:%H:%M}",
        end_date=f"{end_local:%Y-%m-%d}",
        end_time=f"{end_local:%H:%M}",
    )
    return templates.TemplateResponse(request, "calendar/form.html", ctx)


@router.api_route("/{event_id}", methods=["PATCH", "POST"])
async def update_event(
    request: Request,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    event = or_404(await repo.get(event_id))
    body = await parse_body(request)
    if body.get("title") is not None:
        title = str(body["title"]).strip()
        if title:
            event.title = title
    start_raw, end_raw = _combine(body, "start"), _combine(body, "end")
    if start_raw or end_raw:
        try:
            event.starts_at, event.ends_at = _require_times(start_raw, end_raw, _org_tz(org))
        except HTTPException as exc:
            return await _reject(
                request,
                session,
                current_user,
                org,
                body,
                event=event,
                action=f"calendar/{event.id}",
                error=str(exc.detail),
            )
    if body.get("location") is not None:
        event.location = str(body["location"])
    if body.get("description") is not None:
        event.description = str(body["description"])
    await repo.save(event)
    await events.emit(
        CalendarUpdated(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=event.id,
            entity_name=event.title,
        ),
        session,
    )
    if wants_json(request):
        return JSONResponse(CalendarEventRead.model_validate(event).model_dump(mode="json"))
    return RedirectResponse(f"/{org.handle}/calendar/{event.id}", status_code=303)


@router.delete("/{event_id}")
async def delete_event(
    request: Request,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    repo: CalendarRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    event = await repo.get(event_id)
    if event is not None:
        await repo.delete(event)
        await events.emit(
            CalendarDeleted(
                user_id=current_user.id,
                org_id=org_id,
                entity_id=event_id,
                entity_name=event.title,
            ),
            repo.session,
        )
    return delete_response(request, htmx_redirect_url=f"/{org.handle}/calendar")
