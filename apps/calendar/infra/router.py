import calendar as _calendar
import uuid
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.calendar.domain.models import CalendarEvent, CalendarEventRead, format_event_time
from apps.calendar.infra.repository import CalendarEventRepository
from apps.organizations.contract.current import CurrentOrg, CurrentOrgModel
from apps.shared import clock
from apps.shared.http import delete_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context

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


def _parse_dt(raw: str) -> datetime | None:
    s = raw.strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def _require_times(start_raw: str, end_raw: str) -> tuple[datetime, datetime]:
    start = _parse_dt(start_raw)
    end = _parse_dt(end_raw)
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


def _agenda(events: list[CalendarEvent]) -> list[dict]:
    """Events grouped by day, in chronological order — the list the page renders and tests read."""
    groups: list[dict] = []
    for e in events:
        label = f"{e.starts_at:%A}, {e.starts_at.day} {e.starts_at:%B} {e.starts_at.year}"
        if not groups or groups[-1]["label"] != label:
            groups.append({"label": label, "events": []})
        groups[-1]["events"].append(
            {
                "id": str(e.id),
                "title": e.title,
                "time": f"{e.starts_at:%H:%M} – {e.ends_at:%H:%M}",
                "location": e.location,
            }
        )
    return groups


def _month_grid(events: list[CalendarEvent], ref: date, today: date) -> list[list[dict]]:
    by_day: dict[date, list[CalendarEvent]] = {}
    for e in events:
        by_day.setdefault(e.starts_at.date(), []).append(e)
    cal = _calendar.Calendar(firstweekday=0)  # Monday-first, matching the mockup
    weeks = []
    for week in cal.monthdatescalendar(ref.year, ref.month):
        weeks.append(
            [
                {
                    "day": d.day,
                    "in_month": d.month == ref.month,
                    "is_today": d == today,
                    "events": [
                        {"id": str(ev.id), "title": ev.title, "time": f"{ev.starts_at:%H:%M}"}
                        for ev in sorted(by_day.get(d, []), key=lambda x: x.starts_at)
                    ],
                }
                for d in week
            ]
        )
    return weeks


def _ref_month(request: Request) -> date:
    raw = request.query_params.get("month", "")
    parsed = _parse_dt(f"{raw}-01 00:00") if raw else None
    return parsed.date() if parsed else clock.now().date()


def _shift_month(ref: date, months: int) -> str:
    total = ref.year * 12 + (ref.month - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ── routes (org-scoped, RLS, member-only) ──────────────────────────────────────


@router.get("", response_class=HTMLResponse)
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
    ref = _ref_month(request)
    today = clock.now().date()
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        agenda=_agenda(events),
        has_events=bool(events),
        weeks=_month_grid(events, ref, today),
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
        session, current_user, org=org, org_handle=org.handle, event=None, action="calendar"
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
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: CalendarRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    body = await parse_body(request)
    title = str(body.get("title", "")).strip()
    if not title:
        return await _reject(
            request,
            session,
            current_user,
            org,
            body,
            event=body,
            action="calendar",
            error="A title is required",
        )
    try:
        start, end = _require_times(_combine(body, "start"), _combine(body, "end"))
    except HTTPException as exc:
        return await _reject(
            request,
            session,
            current_user,
            org,
            body,
            event=body,
            action="calendar",
            error=str(exc.detail),
        )
    event = await repo.add(
        uuid.UUID(current_user.id),
        title,
        start,
        end,
        location=str(body.get("location", "")),
        description=str(body.get("description", "")),
    )
    audit(
        bg,
        "calendar.created",
        user_id=current_user.id,
        org_id=org_id,
        event_id=str(event.id),
    )
    if wants_json(request):
        return JSONResponse(
            CalendarEventRead.model_validate(event).model_dump(mode="json"), status_code=201
        )
    return RedirectResponse(f"/{org.handle}/calendar/{event.id}", status_code=303)


@router.get("/{event_id}", response_class=HTMLResponse)
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
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=event,
        when=format_event_time(event.starts_at, event.ends_at),
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
    ctx = await fullpage_context(
        session,
        current_user,
        org=org,
        org_handle=org.handle,
        event=event,
        action=f"calendar/{event.id}",
        start_date=f"{event.starts_at:%Y-%m-%d}",
        start_time=f"{event.starts_at:%H:%M}",
        end_date=f"{event.ends_at:%Y-%m-%d}",
        end_time=f"{event.ends_at:%H:%M}",
    )
    return templates.TemplateResponse(request, "calendar/form.html", ctx)


@router.api_route("/{event_id}", methods=["PATCH", "POST"])
async def update_event(
    request: Request,
    bg: BackgroundTasks,
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
            event.starts_at, event.ends_at = _require_times(start_raw, end_raw)
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
    audit(
        bg,
        "calendar.updated",
        user_id=current_user.id,
        org_id=org_id,
        event_id=str(event.id),
    )
    if wants_json(request):
        return JSONResponse(CalendarEventRead.model_validate(event).model_dump(mode="json"))
    return RedirectResponse(f"/{org.handle}/calendar/{event.id}", status_code=303)


@router.delete("/{event_id}")
async def delete_event(
    request: Request,
    bg: BackgroundTasks,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    repo: CalendarRepo,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
) -> Response:
    event = await repo.get(event_id)
    if event is not None:
        await repo.delete(event)
        audit(
            bg,
            "calendar.deleted",
            user_id=current_user.id,
            org_id=org_id,
            event_id=str(event_id),
        )
    return delete_response(request, htmx_redirect_url=f"/{org.handle}/calendar")
