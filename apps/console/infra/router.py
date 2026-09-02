import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import TypedDict, cast

import structlog
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.auth.contract.admin import find_user_id_by_email
from apps.auth.contract.current import CurrentAdmin
from apps.console.contract import appearance
from apps.console.contract.events import (
    AdminGranted,
    AdminRevoked,
    OrgOverrideRemoved,
    OrgOverrideSet,
)
from apps.console.contract.overviews import SECTIONS, ConsoleOverview, ConsoleOverviewQuery
from apps.console.domain import admins, service, technical
from apps.console.domain.admins import AdminNotFound, LastAdminViolation
from apps.console.domain.queue_strip import (
    StripLane,
    axis_ticks,
    bucket_blocks,
    bucket_seconds,
)
from apps.console.domain.service import InvalidSettingValue, UnknownSetting
from apps.console.domain.studio import studio_link
from apps.console.infra.repository import AppSettingRepository
from apps.organizations.contract.queries import list_org_handles
from apps.shared import clock
from apps.shared.charts import day_buckets_series
from apps.shared.events.bus import events
from apps.shared.events.wiring import wiring
from apps.shared.http import JSON_AND_HTML, parse_body, wants_full_page, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.contribs import contribs
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.integration.host import host
from apps.shared.logs.repository import LogRepository
from apps.shared.persistence.database import AdminSession
from apps.shared.queue import (
    TASK_STATES,
    TaskBucket,
    bucketed_runs,
    count_unfinished_tasks,
    list_unfinished_tasks,
    live_recurring_topics,
    unfinished_task_topics,
)
from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import SettingsChanged, SettingsDeclaration

log = structlog.get_logger(__name__)


router = APIRouter(tags=["console"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

# Display metadata for a folded group — ``(title, icon, section)``; see ``_fold_groups``.
_GROUP_DISPLAY: dict[str, tuple[str, str, str]] = {
    "settings": ("Settings", "gear-six", "configuration")
}

_SECTION_LABELS: dict[str, str] = {
    "operations": "Operations",
    "identity": "Identity & access",
    "features": "Features",
    "configuration": "Configuration",
}


def _fold_groups(overviews: list[ConsoleOverview]) -> list[ConsoleOverview]:
    """Fold overviews sharing a ``group`` into one tile, so publishers stay independent.

    Each app still answers ``ConsoleOverviewQuery`` with its own overview; this only affects
    how the grid renders them — same mechanism any future group of tiles can opt into.
    """
    grouped: dict[str, list[ConsoleOverview]] = {}
    folded: list[ConsoleOverview] = []
    for o in overviews:
        if o.group is None:
            folded.append(o)
        else:
            grouped.setdefault(o.group, []).append(o)
    for group, items in grouped.items():
        title, icon, section = _GROUP_DISPLAY.get(group, (group, "folder", "configuration"))
        lines = [line for o in items for line in o.data.get("lines", [])]
        folded.append(
            ConsoleOverview(
                key=group, title=title, icon=icon, section=section, data={"lines": lines}
            )
        )
    return folded


def _sectioned(overviews: list[ConsoleOverview]) -> list[dict]:
    """Group overviews into the console landing sections, in ``SECTIONS`` order.

    Empty sections are dropped; an unknown section label falls back to its raw key.
    """
    sections: list[dict] = []
    for section in SECTIONS:
        members = [o for o in overviews if o.section == section]
        if members:
            label = _SECTION_LABELS.get(section, section)
            sections.append({"key": section, "label": label, "overviews": members})
    return sections


_GROWTH_DAYS = 14


def _growth_chart(overviews: list[ConsoleOverview]) -> dict | None:
    """Fold every tile's ``growth`` slice ({iso_day: n}) into one stacked chart.

    The console stays ignorant of who grows: any app may put a ``growth`` dict in its
    console overview data (profiles and organizations do) and lands on the chart."""
    buckets: dict[str, dict[str, int]] = {}
    names: dict[str, str] = {}
    for o in overviews:
        for day, n in (o.data.get("growth") or {}).items():
            buckets.setdefault(day, {})[o.key] = n
        if o.data.get("growth") is not None:
            names[o.key] = o.data.get("growth_label") or o.title
    if not names:
        return None
    return day_buckets_series(
        buckets, days=_GROWTH_DAYS, end=clock.now().date(), names=names, height=180
    )


async def _raw_overviews(session: AdminSession) -> list[ConsoleOverview]:
    return sorted(await contribs.collect(ConsoleOverviewQuery(session)), key=lambda o: o.key)


async def _collect_overviews(session: AdminSession) -> list[ConsoleOverview]:
    return sorted(_fold_groups(await _raw_overviews(session)), key=lambda o: o.key)


def _group_members(overviews: list[ConsoleOverview], group: str) -> list[ConsoleOverview]:
    return [o for o in overviews if o.group == group]


def _settings_group(app: str) -> SettingsDeclaration:
    group = host.declared_settings(app)
    if group is None:
        raise _NOT_FOUND
    return group


def _overview_for(overviews: list[ConsoleOverview], app: str) -> ConsoleOverview | None:
    return next((o for o in overviews if o.key == app), None)


def _app_event_wiring(app: str) -> dict:
    """The events ``app`` emits and the events it reacts to — read from the event wiring, so no
    app has to report its own wiring (the console asks it directly)."""
    emits = sorted(e.kind for e in wiring.by_app().get(app, []))
    listens = sorted(
        (
            {
                "kind": event_type.kind,
                "owner": wiring.owner_of(event_type) or "?",
                "reaction": r.name,
            }
            for event_type, reactions in wiring.reactions().items()
            for r in reactions
            if r.app == app
        ),
        key=lambda row: (row["kind"], row["reaction"]),
    )
    return {"emits": emits, "listens": listens}


def _event_graph() -> list[dict]:
    """The whole event → reaction graph: every event with a durable consumer, its owner app, and
    each reaction (listening app + name), kind-sorted for a stable console listing."""
    rows = [
        {
            "kind": event_type.kind,
            "owner": wiring.owner_of(event_type) or "?",
            "reactions": sorted(
                ({"app": r.app, "name": r.name} for r in reactions),
                key=lambda r: (r["app"], r["name"]),
            ),
        }
        for event_type, reactions in wiring.reactions().items()
    ]
    return sorted(rows, key=lambda row: row["kind"])


class EventsByApp(TypedDict):
    """Every declared event kind for one app — the full catalogue, wired or not."""

    app: str
    kinds: list[str]


def _events_by_app() -> list[EventsByApp]:
    """Every declared event, grouped by owner app — the full catalogue, wired or not."""
    return [
        EventsByApp(app=app, kinds=sorted(e.kind for e in event_types))
        for app, event_types in wiring.by_app().items()
    ]


async def _supabase_link(
    group: SettingsDeclaration, session: AdminSession
) -> dict[str, str] | None:
    link = group.supabase
    if link is None:
        return None
    settings = get_technical_settings()
    if link.table is not None:
        oid = await AppSettingRepository(session).table_oid(link.table)
        path = (
            f"editor/{oid}?schema={settings.supabase_database_schema}"
            if oid is not None
            else "editor"
        )
    else:
        path = link.path
    href = studio_link(settings.supabase_api_url, path)
    return {"label": link.label, "href": href}


@router.get("", responses=JSON_AND_HTML)
async def get_console(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    overviews = await _collect_overviews(session)
    disabled = await AppSettingRepository(session).disabled_apps()
    if wants_json(request):
        return JSONResponse(
            {
                "overviews": [
                    {"key": o.key, "title": o.title, "disabled": o.key in disabled, **o.data}
                    for o in overviews
                ],
            }
        )
    return templates.TemplateResponse(
        request,
        "console.html",
        {
            "user": current_user,
            "sections": _sectioned(overviews),
            "growth_chart": _growth_chart(overviews),
            "growth_days": _GROWTH_DAYS,
            "disabled": disabled,
            **await fullpage_context(session, current_user),
        },
    )


def _overrides_json(rows: list[dict]) -> list[dict]:
    return [{**o, "org_id": str(o["org_id"])} for o in rows]


def _admins_json(rows: list) -> JSONResponse:
    return JSONResponse({"admins": [{"email": u.email, "is_admin": u.is_admin} for u in rows]})


def _admins_partial(
    request: Request, rows: list, *, error: str | None = None, status_code: int = status.HTTP_200_OK
) -> Response:
    ctx: dict[str, object] = {"admins": rows, "admin_count": len(rows)}
    if error is not None:
        ctx["error"] = error
    return templates.TemplateResponse(request, "console/_admins.html", ctx, status_code=status_code)


# Registered before "/{app}" so "admins" is not captured as an app slug.
@router.get("/admins", responses=JSON_AND_HTML)
async def get_admins(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    rows = await admins.list_admins()
    if wants_json(request):
        return _admins_json(rows)
    return templates.TemplateResponse(
        request,
        "console/admins.html",
        {
            "user": current_user,
            "admins": rows,
            "admin_count": len(rows),
            **await fullpage_context(session, current_user),
        },
    )


# The admin flag itself lives in GoTrue, so the session here carries only the fact — but it carries
# it on a transaction, so a failed journal write fails the request instead of being swallowed.
@router.post("/admins", response_class=HTMLResponse)
async def add_admin(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    body = await parse_body(request)
    email = str(body.get("email") or "").strip()
    try:
        rows = await admins.grant_admin(email)
    except AdminNotFound as exc:
        if wants_json(request):
            return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
        # Matches the JSON branch: "not found by email" is a 404, not a validation failure.
        return _admins_partial(
            request,
            await admins.list_admins(),
            error=exc.email,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    await events.emit(
        AdminGranted(
            user_id=current_user.id, entity_id=await find_user_id_by_email(email), entity_name=email
        ),
        session,
    )
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


@router.put("/admins/{email}", response_class=HTMLResponse)
async def update_admin(
    request: Request, email: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    body = await parse_body(request)
    is_admin = service.coerce_bool(body.get("is_admin"))
    uid = await find_user_id_by_email(email)  # the targeted user, for entity_id correlation
    try:
        rows = await admins.set_admin(email, is_admin=is_admin)
    except AdminNotFound:
        raise _NOT_FOUND from None
    except LastAdminViolation as exc:
        log.warning("settings.last_admin_violation", user_id=str(current_user.id), target=email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    granted: AdminGranted | AdminRevoked = (
        AdminGranted(user_id=current_user.id, entity_id=uid, entity_name=email)
        if is_admin
        else AdminRevoked(user_id=current_user.id, entity_id=uid, entity_name=email)
    )
    await events.emit(granted, session)
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


@router.get("/settings", responses=JSON_AND_HTML)
async def get_settings_page(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    theme_group = _settings_group(appearance.THEME_APP)
    theme_values = await AppSettingRepository(session).values(appearance.THEME_APP)
    theme_settings = service.settings_view(theme_group, theme_values)
    env_vars = technical.env_snapshot()
    process = technical.process_snapshot()
    technical_config = technical.technical_settings_snapshot()
    if wants_json(request):
        return JSONResponse(
            {
                "theme": theme_settings,
                "env_vars": env_vars,
                "process": process,
                "technical_config": technical_config,
            }
        )
    group_overviews = _group_members(await _raw_overviews(session), "settings")
    return templates.TemplateResponse(
        request,
        "console/settings.html",
        {
            "user": current_user,
            "app": appearance.THEME_APP,
            "group_overviews": group_overviews,
            "settings": theme_settings,
            "env_vars": env_vars,
            "process": process,
            "technical_config": technical_config,
            **await fullpage_context(session, current_user),
        },
    )


@router.get("/events", responses=JSON_AND_HTML)
async def get_events(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    """The event → reaction graph across the whole system — what each app emits and who reacts."""
    graph = _event_graph()
    by_app = _events_by_app()
    if wants_json(request):
        return JSONResponse({"events": graph, "by_app": by_app})
    return templates.TemplateResponse(
        request,
        "console/events.html",
        {
            "user": current_user,
            "graph": graph,
            "by_app": by_app,
            **await fullpage_context(session, current_user),
        },
    )


# The history's default reach. Six hours shows an hourly recurring topic as a readable comb and
# still fits a morning's incidents; anything wider is asked for explicitly.
_HISTORY_WINDOW = timedelta(hours=6)
# The two lines a failed try writes; nothing is logged for a task that simply succeeded.
_ATTEMPT_LINES = ("queue.task_retrying", "queue.task_failed")


def _window_bound(value: str) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value as UTC; empty means "left alone".

    The console reads and writes UTC throughout (its columns say so), so a bare local-looking
    value is taken at face value rather than guessed at.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC)
    except ValueError:
        return None


def _history_window(from_dt: str, to_dt: str) -> tuple[datetime, datetime]:
    end = _window_bound(to_dt) or clock.now()
    start = _window_bound(from_dt) or end - _HISTORY_WINDOW
    return (start, end) if start < end else (end - _HISTORY_WINDOW, end)


def _cadence(seconds: int | None) -> str:
    """How often a recurring topic comes round, in the words a reader thinks in."""
    if not seconds:
        return ""
    for unit, size in (("day", 86400), ("hour", 3600), ("min", 60)):
        if seconds >= size and seconds % size == 0:
            count = seconds // size
            return f"every {unit}" if count == 1 else f"every {count} {unit}s"
    return f"every {seconds}s"


def _ran(runs: int) -> str:
    return f"{runs} run" if runs == 1 else f"{runs} runs"


def _lanes(
    counted: list[TaskBucket],
    attempts: dict[tuple[str, datetime], int],
    bucket: int,
    start: datetime,
    end: datetime,
) -> list[StripLane]:
    """One lane per topic, one block per slot of time — every run in the window, none capped.

    What each lane says in its margins is the caller's: the two families differ only there, and
    threading that difference through here as a pair of callables was more machinery than the
    difference is worth.

    A slot with no queue row but with failed tries logged still gets its block: a task retrying
    across the window has written lines and not yet landed anywhere, and a lane that waited for it
    to finish would show nothing at all while it was going wrong.
    """
    by_topic: dict[str, dict[datetime, dict[str, int]]] = {}
    for one in counted:
        by_topic.setdefault(one.topic, {}).setdefault(one.slot, {})[one.state] = one.runs
    # A slot with tries logged but no queue row is a task still going wrong: it has written lines
    # and landed nowhere, and a lane that waited for it to finish would show nothing meanwhile.
    for topic, slot in attempts:
        by_topic.setdefault(topic, {}).setdefault(slot, {})

    lanes = []
    for topic, slots in sorted(by_topic.items()):
        blocks = [
            block
            for slot, counts in sorted(slots.items())
            for block in bucket_blocks(
                slot_start=slot,
                slot_end=slot + timedelta(seconds=bucket),
                topic=topic,
                counts=counts,
                attempts=attempts.get((topic, slot), 0),
                window_start=start,
                window_end=end,
            )
        ]
        totals = list(slots.values())
        lanes.append(
            StripLane(
                key=topic,
                title=topic,
                subtitle="",
                badge="",
                state="parked" if any("parked" in c for c in totals) else "done",
                runs=sum(sum(c.values()) for c in totals),
                segments=blocks,
            )
        )
    return lanes


async def _history(session: AdminSession, from_dt: str, to_dt: str) -> dict[str, object]:
    """Both families of lane over one window, the recurring pinned above the one-shots.

    Everything is counted in Postgres — the runs and the failed tries alike — so the window may
    hold ten rows or ten thousand and the screen draws the same few hundred blocks.
    """
    start, end = _history_window(from_dt, to_dt)
    bucket = bucket_seconds(start, end)
    cadences = await live_recurring_topics(session)
    attempts = await LogRepository(session).counted_by_payload_key(
        "topic", names=_ATTEMPT_LINES, since=start, until=end, bucket=bucket
    )

    recurring_lanes = [
        replace(lane, badge=_cadence(cadences.get(lane.key)))
        for lane in _lanes(
            await bucketed_runs(session, since=start, until=end, bucket=bucket, recurring=True),
            {k: v for k, v in attempts.items() if k[0] in cadences},
            bucket,
            start,
            end,
        )
    ]
    # A recurring topic keeps its lane even when the window caught nothing: it is a permanent
    # fixture, and a lane that disappears on a quiet hour reads as the topic having been removed.
    drawn = {lane.key for lane in recurring_lanes}
    recurring_lanes += [
        StripLane(
            key=t, title=t, subtitle="", badge=_cadence(every), state="done", runs=0, segments=[]
        )
        for t, every in cadences.items()
        if t not in drawn
    ]
    oneshot_lanes = [
        replace(lane, subtitle=_ran(lane.runs), badge=lane.state)
        for lane in _lanes(
            await bucketed_runs(session, since=start, until=end, bucket=bucket, recurring=False),
            {k: v for k, v in attempts.items() if k[0] not in cadences},
            bucket,
            start,
            end,
        )
    ]
    now = clock.now()
    return {
        "window_start": start,
        "window_end": end,
        "bucket_seconds": bucket,
        # A window with no blocks looks exactly like a broken screen, because the recurring lanes
        # are drawn whatever it holds. Both reasons are said out loud instead — and the commonest
        # is a window typed off a wall clock while the bounds are read as UTC.
        "window_ahead": start > now,
        "has_runs": any(lane.segments for lane in [*recurring_lanes, *oneshot_lanes]),
        "now_utc": now.strftime("%H:%M"),
        "axis": axis_ticks(start, end),
        "recurring_lanes": sorted(recurring_lanes, key=lambda lane: lane.key),
        "oneshot_lanes": oneshot_lanes,
        "from_dt": from_dt,
        "to_dt": to_dt,
    }


@router.get("/queue", responses=JSON_AND_HTML)
async def get_queue(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    state: str = "",
    topic: str = "",
    from_dt: str = "",
    to_dt: str = "",
    panel: str = "",
) -> Response:
    """The async substrate, read two ways: what it still owes, and what it ran.

    Declared before ``/{app}``: the catch-all below would answer ``/console/queue`` with a
    settings page for an app named "queue", and FastAPI matches in registration order.
    """
    if state and state not in TASK_STATES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown state")
    tasks = await list_unfinished_tasks(session, state=state, topic=topic)
    counts = await count_unfinished_tasks(session)
    context: dict[str, object] = {
        "tasks": tasks,
        "state_filter": state,
        "topic_filter": topic,
    }
    if not wants_json(request) and not wants_full_page(request):
        # A filter's own swap. Which panel asked is stated by the form rather than guessed from
        # which fields it carries: "back to live" sends empty bounds, and empty is also what the
        # backlog sends. Each filter replaces only its own panel — a full GET would reload the
        # page onto the server-rendered default tab, throwing the reader out of the one they were
        # reading.
        if panel == "history":
            return templates.TemplateResponse(
                request, "console/_queue_history.html", await _history(session, from_dt, to_dt)
            )
        return templates.TemplateResponse(request, "console/_queue_tasks.html", context)
    history = await _history(session, from_dt, to_dt)
    if wants_json(request):
        return JSONResponse(
            {
                "tasks": [t.model_dump(mode="json") for t in tasks],
                "counts": counts,
                "history": _history_json(history),
            }
        )
    return templates.TemplateResponse(
        request,
        "console/queue.html",
        {
            "user": current_user,
            "counts": counts,
            "states": TASK_STATES,
            "topics": await unfinished_task_topics(session),
            **context,
            **history,
            **await fullpage_context(session, current_user),
        },
    )


def _history_json(history: dict[str, object]) -> dict[str, object]:
    """The same lanes a machine can read — the strip is a picture, its data is not."""
    lanes = [
        {
            "key": lane.key,
            "topic": lane.title,
            "state": lane.state,
            "badge": lane.badge,
            "family": family,
            "segments": [
                {
                    "kind": s.kind,
                    "left": s.left,
                    "width": s.width,
                    "starts_at": s.starts_at.isoformat(),
                    "ends_at": s.ends_at.isoformat(),
                }
                for s in lane.segments
            ],
        }
        for family, key in (("recurring", "recurring_lanes"), ("one-shot", "oneshot_lanes"))
        for lane in cast("list[StripLane]", history[key])
    ]
    return {
        "from": cast("datetime", history["window_start"]).isoformat(),
        "to": cast("datetime", history["window_end"]).isoformat(),
        "lanes": lanes,
    }


@router.get("/{app}", responses=JSON_AND_HTML)
async def get_app(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = _settings_group(app)
    overview = _overview_for(await _collect_overviews(session), app)
    event_wiring = _app_event_wiring(app)
    repo = AppSettingRepository(session)
    values = await repo.values(app)
    settings = service.settings_view(group, values)
    org_overrides = await repo.org_overrides(app)
    supabase = await _supabase_link(group, session)
    if wants_json(request):
        return JSONResponse(
            {
                "app": app,
                "settings": settings,
                "org_overrides": _overrides_json(org_overrides),
                "supabase": supabase,
                "links": [{"label": link.label, "href": link.href} for link in group.links],
            }
        )
    return templates.TemplateResponse(
        request,
        "console/app.html",
        {
            "user": current_user,
            "app": app,
            "overview": overview,
            "event_wiring": event_wiring,
            "settings": settings,
            "org_overrides": org_overrides,
            "org_handles": await list_org_handles(session),
            "supabase": supabase,
            "links": group.links,
            **await fullpage_context(session, current_user),
        },
    )


async def _render_org_overrides(
    request: Request, session, app: str, group: SettingsDeclaration, error: str | None = None
) -> Response:
    repo = AppSettingRepository(session)
    org_overrides = await repo.org_overrides(app)
    if wants_json(request):
        if error is not None:
            return JSONResponse({"detail": error}, status_code=status.HTTP_400_BAD_REQUEST)
        return JSONResponse({"app": app, "org_overrides": _overrides_json(org_overrides)})
    return templates.TemplateResponse(
        request,
        "console/_org_settings.html",
        {
            "app": app,
            "org_overrides": org_overrides,
            "settings": service.settings_view(group, {}),
            "org_handles": await list_org_handles(session),
            "org_error": error,
        },
        status_code=status.HTTP_400_BAD_REQUEST if error else status.HTTP_200_OK,
    )


@router.post("/{app}/org-settings", response_class=HTMLResponse)
async def create_org_override(
    request: Request,
    app: str,
    current_user: CurrentAdmin,
    session: AdminSession,
) -> Response:
    group = _settings_group(app)
    body = await parse_body(request)
    handle = str(body.get("org_handle", "")).strip().lower()
    key = str(body.get("key", ""))
    value = str(body.get("value", ""))
    repo = AppSettingRepository(session)

    if not any(d.key == key and d.org_overridable for d in group.defs):
        return await _render_org_overrides(
            request, session, app, group, error=f"'{key}' cannot be overridden per organisation."
        )

    org_id = await repo.org_id_by_handle(handle)
    if org_id is None:
        return await _render_org_overrides(
            request, session, app, group, error=f"No organisation with handle '{handle}'."
        )
    try:
        stored = service.validate(group, key, value)
    except UnknownSetting:
        raise _NOT_FOUND from None
    except InvalidSettingValue as exc:
        return await _render_org_overrides(request, session, app, group, error=str(exc))

    await repo.set_org_override(app, key, org_id, stored)
    await session.commit()
    await events.emit(
        OrgOverrideSet(
            user_id=current_user.id,
            org_id=org_id,
            app=app,
            key=key,
            value=stored,
            entity_name=f"{app}.{key}",  # the setting is the subject: name it for the timeline
        ),
        session,
    )
    return await _render_org_overrides(request, session, app, group)


@router.delete("/{app}/org-settings/{key}/{org_id}", response_class=HTMLResponse)
async def delete_org_override(
    request: Request,
    app: str,
    key: str,
    org_id: uuid.UUID,
    current_user: CurrentAdmin,
    session: AdminSession,
) -> Response:
    group = _settings_group(app)
    repo = AppSettingRepository(session)
    await repo.delete_org_override(app, key, org_id)
    await session.commit()
    await events.emit(
        OrgOverrideRemoved(
            user_id=current_user.id, org_id=org_id, app=app, key=key, entity_name=f"{app}.{key}"
        ),
        session,
    )
    return await _render_org_overrides(request, session, app, group)


@router.put("/{app}/settings/{key}", response_class=HTMLResponse)
async def update_setting(
    request: Request, app: str, key: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = _settings_group(app)
    body = await parse_body(request)
    value = str(body.get("value", ""))
    try:
        stored = service.validate(group, key, value)
    except UnknownSetting:
        raise _NOT_FOUND from None
    except InvalidSettingValue as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    repo = AppSettingRepository(session)
    await repo.set(app, key, stored)
    values = await repo.values(app)
    # One fact: SettingsChanged is persisted as the audit record (who changed what) AND fires the
    # spread NOTIFY (delivered on commit) so every instance re-reads and reloads — atomic with the
    # write, all on this session, committed together.
    await events.emit(
        SettingsChanged(
            user_id=current_user.id,
            target_app=app,
            key=key,
            value=stored,
            values=values,
            # `target_app` routes the reload; `entity_name` is what a human reads in the timeline.
            entity_name=f"{app}.{key}",
        ),
        session=session,
    )
    await session.commit()
    settings = service.settings_view(group, values)
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings})
    return templates.TemplateResponse(
        request, "console/_settings.html", {"app": app, "settings": settings, "saved_key": key}
    )
