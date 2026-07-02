from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import SettingsChanged, SettingsGroup, declared_settings
from apps.settings.domain import admins, service
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


async def _collect_overviews(session: AdminSession) -> list[ConsoleOverview]:
    overviews = await host.events.collect(ConsoleOverviewQuery(session))
    return sorted(overviews, key=lambda o: o.key)


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


@router.get("/logs", response_class=HTMLResponse)
async def get_logs(request: Request, current_user: CurrentAdmin, session: AdminSession) -> Response:
    entries, next_before_id = await _search_logs(
        session, level="", event="", from_dt="", to_dt="", before_id=None
    )
    if wants_json(request):
        return JSONResponse({"entries": entries, "next_before_id": next_before_id})
    return templates.TemplateResponse(
        request,
        "console/logs.html",
        {
            "user": current_user,
            "entries": entries,
            "next_before_id": next_before_id,
            "level": "",
            "event": "",
            "from_dt": "",
            "to_dt": "",
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
