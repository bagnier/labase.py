import uuid

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
from apps.console.domain.service import InvalidSettingValue, UnknownSetting
from apps.console.domain.studio import studio_link
from apps.console.infra.repository import AppSettingRepository
from apps.organizations.contract.queries import list_org_handles
from apps.shared import clock
from apps.shared.charts import day_buckets_series
from apps.shared.events.bus import events
from apps.shared.events.wiring import wiring
from apps.shared.http import JSON_AND_HTML, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.contribs import contribs
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.integration.host import host
from apps.shared.persistence.database import AdminSession
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
    if wants_json(request):
        return JSONResponse({"events": graph})
    return templates.TemplateResponse(
        request,
        "console/events.html",
        {"user": current_user, "graph": graph, **await fullpage_context(session, current_user)},
    )


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
