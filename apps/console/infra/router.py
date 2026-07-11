import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.console.contract import appearance
from apps.console.contract.overviews import SECTIONS, ConsoleOverview, ConsoleOverviewQuery
from apps.console.domain import admins, service, technical
from apps.console.domain.admins import AdminNotFound, LastAdminViolation
from apps.console.domain.service import InvalidSettingValue, UnknownSetting
from apps.console.infra.repository import AppSettingRepository
from apps.organizations.contract.queries import list_org_handles
from apps.shared import clock
from apps.shared.bus import bus
from apps.shared.charts import day_buckets_series
from apps.shared.config import get_technical_settings
from apps.shared.host import host
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.settings import SettingsChanged, SettingsDeclaration
from apps.shared.supabase_studio import studio_link

router = APIRouter(tags=["console"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

# Display metadata for folded groups — (title, icon, section); see _fold_groups.
_GROUP_DISPLAY: dict[str, tuple[str, str, str]] = {
    "settings": ("Settings", "gear-six", "configuration")
}

# Human labels for the console landing sections (order comes from SECTIONS).
_SECTION_LABELS: dict[str, str] = {
    "operations": "Operations",
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
            names[o.key] = o.title
    if not names:
        return None
    return day_buckets_series(
        buckets, days=_GROWTH_DAYS, end=clock.now().date(), names=names, height=180
    )


async def _raw_overviews(session: AdminSession) -> list[ConsoleOverview]:
    return sorted(await bus.collect(ConsoleOverviewQuery(session)), key=lambda o: o.key)


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


@router.get("", response_class=HTMLResponse)
async def get_console(
    request: Request, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    overviews = await _collect_overviews(session)
    disabled = await AppSettingRepository(session).disabled_apps()
    links = host.declared_console_links()
    if wants_json(request):
        return JSONResponse(
            {
                "overviews": [
                    {"key": o.key, "title": o.title, "disabled": o.key in disabled, **o.data}
                    for o in overviews
                ],
                "links": [{"label": link.label, "href": link.href} for link in links],
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
            "links": links,
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
            **await fullpage_context(session, current_user),
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
        # Matches the JSON branch: "not found by email" is a 404, not a validation failure.
        return _admins_partial(
            request,
            await admins.list_admins(),
            error=exc.email,
            status_code=status.HTTP_404_NOT_FOUND,
        )
    audit(
        bg,
        "settings.admin_granted",
        level="warning",
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
        audit(
            bg,
            "settings.last_admin_violation",
            level="warning",
            user_id=current_user.id,
            target_email=email,
            ip=request.client.host if request.client else None,
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    audit(
        bg,
        "settings.admin_granted" if is_admin else "settings.admin_revoked",
        level="warning",
        user_id=current_user.id,
        target_email=email,
    )
    if wants_json(request):
        return _admins_json(rows)
    return _admins_partial(request, rows)


@router.get("/settings", response_class=HTMLResponse)
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


@router.get("/{app}", response_class=HTMLResponse)
async def get_app(
    request: Request, app: str, current_user: CurrentAdmin, session: AdminSession
) -> Response:
    group = _settings_group(app)
    overview = _overview_for(await _collect_overviews(session), app)
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
    bg: BackgroundTasks,
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
    audit(
        bg,
        "settings.org_override_set",
        user_id=current_user.id,
        org_id=org_id,
        app=app,
        key=key,
        value=stored,
    )
    return await _render_org_overrides(request, session, app, group)


@router.delete("/{app}/org-settings/{key}/{org_id}", response_class=HTMLResponse)
async def delete_org_override(
    request: Request,
    bg: BackgroundTasks,
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
    audit(
        bg,
        "settings.org_override_removed",
        user_id=current_user.id,
        org_id=org_id,
        app=app,
        key=key,
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
    await session.commit()

    values = await repo.values(app)
    await bus.emit(SettingsChanged(app, values))
    settings = service.settings_view(group, values)
    if wants_json(request):
        return JSONResponse({"app": app, "settings": settings})
    return templates.TemplateResponse(
        request, "console/_settings.html", {"app": app, "settings": settings, "saved_key": key}
    )
