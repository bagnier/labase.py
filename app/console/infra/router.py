from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.auth.contract.admin import (
    find_user_id_by_email,
    list_server_admins,
    set_server_admin,
)
from app.auth.contract.current import CurrentAdmin
from app.console.contract.features import TOGGLEABLE_APPS
from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import ConsoleSettingsQuery, SettingsGroup
from app.console.domain import service
from app.console.domain.admins import LastAdminViolation, ensure_not_last_admin
from app.console.domain.service import InvalidSettingValue, UnknownSetting
from app.console.infra.repository import AppSettingRepository
from app.shared.config import get_settings
from app.shared.host import host
from app.shared.http import parse_body, wants_json
from app.shared.http.templates import templates
from app.shared.persistence.database import AdminSession
from app.shared.supabase_studio import studio_link

router = APIRouter(tags=["console"])


def _coerce_bool(raw: object) -> bool:
    return raw is True or str(raw).lower() == "true"


async def _overviews(session: AdminSession) -> list[ConsoleOverview]:
    overviews = await host.events.collect(ConsoleOverviewQuery(session))
    return sorted(overviews, key=lambda o: o.key)


async def _settings_group(app: str) -> SettingsGroup:
    groups = await host.events.collect(ConsoleSettingsQuery())
    for group in groups:
        if group.app == app:
            return group
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _overview_for(overviews: list[ConsoleOverview], app: str) -> ConsoleOverview | None:
    return next((o for o in overviews if o.key == app), None)


async def _supabase_link(group: SettingsGroup, session: AdminSession) -> dict[str, str] | None:
    link = group.supabase
    if link is None:
        return None
    settings = get_settings()
    if link.table is not None:
        oid = await AppSettingRepository(session).table_oid(link.table)
        path = f"editor/{oid}?schema={settings.db_schema}" if oid is not None else "editor"
    else:
        path = link.path
    href = studio_link(settings.supabase_url, path)
    return {"label": link.label, "href": href}


@router.get("", response_class=HTMLResponse)
async def console_index(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    overviews = await _overviews(session)
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
        {"user": current_user, "overviews": overviews, "disabled": disabled},
    )


def _admin_rows(users: list) -> list:
    return sorted((u for u in users if u.is_admin), key=lambda u: u.email)


def _admins_json(admins: list) -> JSONResponse:
    return JSONResponse({"admins": [{"email": u.email, "is_admin": u.is_admin} for u in admins]})


# Registered before "/{app}" so "admins" is not captured as an app slug.
@router.get("/admins", response_class=HTMLResponse)
async def console_admins(request: Request, current_user: CurrentAdmin) -> Response:
    admins = _admin_rows(await list_server_admins())
    if wants_json(request):
        return _admins_json(admins)
    return templates.TemplateResponse(
        request,
        "console/admins.html",
        {"user": current_user, "admins": admins, "admin_count": len(admins)},
    )


@router.post("/admins", response_class=HTMLResponse)
async def add_admin(request: Request, current_user: CurrentAdmin) -> Response:
    body = await parse_body(request)
    email = str(body.get("email") or "").strip()
    uid = await find_user_id_by_email(email) if email else None
    if uid is None:
        if wants_json(request):
            return JSONResponse(
                {"detail": f"No account exists for {email}"},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        admins = _admin_rows(await list_server_admins())
        return templates.TemplateResponse(
            request,
            "console/_admins.html",
            {"admins": admins, "admin_count": len(admins), "error": email},
        )

    await set_server_admin(uid, True)
    admins = _admin_rows(await list_server_admins())
    if wants_json(request):
        return _admins_json(admins)
    return templates.TemplateResponse(
        request, "console/_admins.html", {"admins": admins, "admin_count": len(admins)}
    )


@router.put("/admins/{email}", response_class=HTMLResponse)
async def update_admin(request: Request, email: str, current_user: CurrentAdmin) -> Response:
    body = await parse_body(request)
    is_admin = _coerce_bool(body.get("is_admin"))
    uid = await find_user_id_by_email(email)
    if uid is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    users = await list_server_admins()
    target_is_admin = any(u.user_id == uid and u.is_admin for u in users)
    admin_count = sum(1 for u in users if u.is_admin)
    try:
        ensure_not_last_admin(
            is_revoke=not is_admin, target_is_admin=target_is_admin, admin_count=admin_count
        )
    except LastAdminViolation as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    await set_server_admin(uid, is_admin)

    admins = _admin_rows(await list_server_admins())
    if wants_json(request):
        return _admins_json(admins)
    return templates.TemplateResponse(
        request, "console/_admins.html", {"admins": admins, "admin_count": len(admins)}
    )


@router.get("/{app}", response_class=HTMLResponse)
async def console_app(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = await _settings_group(app)
    overview = _overview_for(await _overviews(session), app)
    overrides = await AppSettingRepository(session).overrides(app)
    settings = service.effective_settings(group, overrides)
    supabase = await _supabase_link(group, session)
    toggleable = app in TOGGLEABLE_APPS
    enabled = overrides.get("enabled", "true") == "true"
    if wants_json(request):
        return JSONResponse(
            {"app": app, "settings": settings, "supabase": supabase, "enabled": enabled}
        )
    return templates.TemplateResponse(
        request,
        "console/app.html",
        {
            "user": current_user,
            "app": app,
            "overview": overview,
            "settings": settings,
            "supabase": supabase,
            "toggleable": toggleable,
            "enabled": enabled,
        },
    )


@router.put("/{app}/settings/{key}", response_class=HTMLResponse)
async def update_setting(
    request: Request, app: str, key: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = await _settings_group(app)
    body = await parse_body(request)
    value = str(body.get("value", ""))
    try:
        stored = service.validate(group, key, value)
    except UnknownSetting:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None
    except InvalidSettingValue as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    repo = AppSettingRepository(session)
    await repo.set(app, key, stored)
    await session.commit()

    settings = service.effective_settings(group, await repo.overrides(app))
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings})
    return templates.TemplateResponse(
        request, "console/_settings.html", {"app": app, "settings": settings, "saved_key": key}
    )


@router.put("/{app}/enabled", response_class=HTMLResponse)
async def update_enabled(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    if app not in TOGGLEABLE_APPS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    value = "true" if _coerce_bool(body.get("value")) else "false"

    repo = AppSettingRepository(session)
    await repo.set(app, "enabled", value)
    await session.commit()

    enabled = value == "true"
    if wants_json(request):
        return JSONResponse({"app": app, "enabled": enabled})
    return templates.TemplateResponse(
        request, "console/_enabled.html", {"app": app, "enabled": enabled, "toggleable": True}
    )
