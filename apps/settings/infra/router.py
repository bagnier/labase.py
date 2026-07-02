from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.settings.contract import appearance
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import SettingsChanged, SettingsGroup, declared_settings
from apps.settings.domain import admins, service, technical
from apps.settings.domain.admins import AdminNotFound, LastAdminViolation
from apps.settings.domain.service import InvalidSettingValue, UnknownSetting
from apps.settings.infra.audit_log_repository import AuditLogRepository, parse_range_bound
from apps.settings.infra.repository import AppSettingRepository
from apps.shared.config import get_technical_settings
from apps.shared.host import host
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import record_audit_event
from apps.shared.page import shell_context
from apps.shared.persistence.database import AdminSession
from apps.shared.supabase_studio import studio_link

router = APIRouter(tags=["console"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

# Display metadata for folded groups — see _fold_groups.
_GROUP_DISPLAY: dict[str, tuple[str, str]] = {"settings": ("Settings", "gear-six")}


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
        title, icon = _GROUP_DISPLAY.get(group, (group, "folder"))
        lines = [line for o in items for line in o.data.get("lines", [])]
        folded.append(ConsoleOverview(key=group, title=title, icon=icon, data={"lines": lines}))
    return folded


async def _raw_overviews(session: AdminSession) -> list[ConsoleOverview]:
    return sorted(await host.events.collect(ConsoleOverviewQuery(session)), key=lambda o: o.key)


async def _collect_overviews(session: AdminSession) -> list[ConsoleOverview]:
    return sorted(_fold_groups(await _raw_overviews(session)), key=lambda o: o.key)


def _group_members(overviews: list[ConsoleOverview], group: str) -> list[ConsoleOverview]:
    return [o for o in overviews if o.group == group]


def _settings_group(app: str) -> SettingsGroup:
    group = declared_settings(app)
    if group is None:
        raise _NOT_FOUND
    return group


def _overview_for(overviews: list[ConsoleOverview], app: str) -> ConsoleOverview | None:
    return next((o for o in overviews if o.key == app), None)


async def _supabase_link(group: SettingsGroup, session: AdminSession) -> dict[str, str] | None:
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


@router.get("", response_class=HTMLResponse)
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
                ]
            }
        )
    return templates.TemplateResponse(
        request,
        "console.html",
        {
            "user": current_user,
            "overviews": overviews,
            "disabled": disabled,
            **await shell_context(session, current_user),
        },
    )


def _admins_json(rows: list) -> JSONResponse:
    return JSONResponse({"admins": [{"email": u.email, "is_admin": u.is_admin} for u in rows]})


def _admins_partial(request: Request, rows: list, *, error: str | None = None) -> Response:
    ctx: dict[str, object] = {"admins": rows, "admin_count": len(rows)}
    if error is not None:
        ctx["error"] = error
    return templates.TemplateResponse(request, "console/_admins.html", ctx)


# Registered before "/{app}" so "admins" is not captured as an app slug.
@router.get("/admins", response_class=HTMLResponse)
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
            **await shell_context(session, current_user),
        },
    )


@router.post("/admins", response_class=HTMLResponse)
async def add_admin(request: Request, current_user: CurrentAdmin, bg: BackgroundTasks) -> Response:
    body = await parse_body(request)
    email = str(body.get("email") or "").strip()
    try:
        rows = await admins.grant_admin(email)
    except AdminNotFound as exc:
        if wants_json(request):
            return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
        return _admins_partial(request, await admins.list_admins(), error=exc.email)
    record_audit_event(
        bg,
        level="warning",
        event="settings.admin_granted",
        user_id=current_user.id,
        target_email=email,
    )
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


@router.put("/admins/{email}", response_class=HTMLResponse)
async def update_admin(
    request: Request, email: str, current_user: CurrentAdmin, bg: BackgroundTasks
) -> Response:
    body = await parse_body(request)
    is_admin = service.coerce_bool(body.get("is_admin"))
    try:
        rows = await admins.set_admin(email, is_admin=is_admin)
    except AdminNotFound:
        raise _NOT_FOUND from None
    except LastAdminViolation as exc:
        record_audit_event(
            bg,
            level="warning",
            event="settings.last_admin_violation",
            user_id=current_user.id,
            target_email=email,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    record_audit_event(
        bg,
        level="warning",
        event="settings.admin_granted" if is_admin else "settings.admin_revoked",
        user_id=current_user.id,
        target_email=email,
    )
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


_LOG_PAGE_SIZE = 50


def _paginate(rows: list[dict], limit: int) -> tuple[list[dict], int | None]:
    """Split a ``limit + 1``-fetched page: the visible rows and the next cursor, if any."""
    if len(rows) > limit:
        return rows[:limit], rows[limit - 1]["id"]
    return rows, None


async def _search_logs(
    session: AdminSession,
    *,
    level: str,
    event: str,
    from_dt: str,
    to_dt: str,
    before_id: int | None,
) -> tuple[list[dict], int | None]:
    rows = await AuditLogRepository(session).search(
        level=level or None,
        event=event or None,
        from_dt=parse_range_bound(from_dt),
        to_dt=parse_range_bound(to_dt),
        before_id=before_id,
        limit=_LOG_PAGE_SIZE,
    )
    return _paginate(rows, _LOG_PAGE_SIZE)


@router.get("/settings", response_class=HTMLResponse)
async def get_settings_page(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    theme_group = _settings_group(appearance.THEME_APP)
    theme_values = await AppSettingRepository(session).values(appearance.THEME_APP)
    theme_settings = service.settings_view(theme_group, theme_values)
    entries, next_before_id = await _search_logs(
        session, level="", event="", from_dt="", to_dt="", before_id=None
    )
    env_vars = technical.env_snapshot()
    process = technical.process_snapshot()
    technical_config = technical.technical_settings_snapshot()
    if wants_json(request):
        return JSONResponse(
            {
                "theme": theme_settings,
                "entries": entries,
                "next_before_id": next_before_id,
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
            "entries": entries,
            "next_before_id": next_before_id,
            "level": "",
            "event": "",
            "from_dt": "",
            "to_dt": "",
            "env_vars": env_vars,
            "process": process,
            "technical_config": technical_config,
            **await shell_context(session, current_user),
        },
    )


# Registered before "/{app}" so "logs" is not captured as an app slug.
@router.get("/logs/entries", response_class=HTMLResponse)
async def get_log_entries(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    level: str = "",
    event: str = "",
    from_dt: str = "",
    to_dt: str = "",
    before_id: int | None = None,
) -> Response:
    entries, next_before_id = await _search_logs(
        session, level=level, event=event, from_dt=from_dt, to_dt=to_dt, before_id=before_id
    )
    if wants_json(request):
        return JSONResponse({"entries": entries, "next_before_id": next_before_id})
    return templates.TemplateResponse(
        request,
        "console/_log_entries.html",
        {
            "entries": entries,
            "next_before_id": next_before_id,
            "level": level,
            "event": event,
            "from_dt": from_dt,
            "to_dt": to_dt,
            "appending": before_id is not None,
        },
    )


@router.get("/{app}", response_class=HTMLResponse)
async def get_app(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = _settings_group(app)
    overview = _overview_for(await _collect_overviews(session), app)
    values = await AppSettingRepository(session).values(app)
    settings = service.settings_view(group, values)
    supabase = await _supabase_link(group, session)
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings, "supabase": supabase})
    return templates.TemplateResponse(
        request,
        "console/app.html",
        {
            "user": current_user,
            "app": app,
            "overview": overview,
            "settings": settings,
            "supabase": supabase,
            **await shell_context(session, current_user),
        },
    )


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
    await session.commit()

    values = await repo.values(app)
    await host.events.emit(SettingsChanged(app, values))
    settings = service.settings_view(group, values)
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings})
    return templates.TemplateResponse(
        request, "console/_settings.html", {"app": app, "settings": settings, "saved_key": key}
    )
