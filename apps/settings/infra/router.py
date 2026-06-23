from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.profile.contract.shell import shell_context
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import SettingsChanged, SettingsGroup, declared_settings
from apps.settings.domain import admins, service
from apps.settings.domain.admins import AdminNotFound, LastAdminViolation
from apps.settings.domain.service import InvalidSettingValue, UnknownSetting
from apps.settings.infra.repository import AppSettingRepository
from apps.shared.config import get_technical_settings
from apps.shared.host import host
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
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
        path = f"editor/{oid}?schema={settings.db_schema}" if oid is not None else "editor"
    else:
        path = link.path
    href = studio_link(settings.supabase_url, path)
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
async def add_admin(request: Request, current_user: CurrentAdmin) -> Response:
    body = await parse_body(request)
    email = str(body.get("email") or "").strip()
    try:
        rows = await admins.grant_admin(email)
    except AdminNotFound as exc:
        if wants_json(request):
            return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_404_NOT_FOUND)
        return _admins_partial(request, await admins.list_admins(), error=exc.email)
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


@router.put("/admins/{email}", response_class=HTMLResponse)
async def update_admin(request: Request, email: str, current_user: CurrentAdmin) -> Response:
    body = await parse_body(request)
    is_admin = service.coerce_bool(body.get("is_admin"))
    try:
        rows = await admins.set_admin(email, is_admin=is_admin)
    except AdminNotFound:
        raise _NOT_FOUND from None
    except LastAdminViolation as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


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
