from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.auth.contract.current import CurrentAdmin
from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import ConsoleSettingsQuery, SettingsGroup
from app.console.domain import service
from app.console.domain.service import InvalidSettingValue, UnknownSetting
from app.console.infra.repository import AppSettingRepository
from app.shared.host import host
from app.shared.http import parse_body, wants_json
from app.shared.http.templates import templates
from app.shared.persistence.database import AdminSession

router = APIRouter(tags=["console"])


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


@router.get("", response_class=HTMLResponse)
async def console_index(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    overviews = await _overviews(session)
    if wants_json(request):
        return JSONResponse(
            {"overviews": [{"key": o.key, "title": o.title, **o.data} for o in overviews]}
        )
    return templates.TemplateResponse(
        request, "console.html", {"user": current_user, "overviews": overviews}
    )


@router.get("/{app}", response_class=HTMLResponse)
async def console_app(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = await _settings_group(app)
    overview = _overview_for(await _overviews(session), app)
    overrides = await AppSettingRepository(session).overrides(app)
    settings = service.effective_settings(group, overrides)
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings})
    return templates.TemplateResponse(
        request,
        "console/app.html",
        {"user": current_user, "app": app, "overview": overview, "settings": settings},
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
        request, "console/_settings.html", {"app": app, "settings": settings}
    )
