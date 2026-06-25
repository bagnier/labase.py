"""How the public context plugs into the running app: mounts the landing-page router."""

from fastapi import FastAPI

from apps.public.contract import settings
from apps.public.infra.router import router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    declare_app_settings,
)
from apps.shared.host import Host


def mount(app: FastAPI, host: Host) -> None:
    _declare_settings()
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    app.include_router(router)
    host.events.on(ConsoleOverviewQuery, _console_overview)


def _declare_settings() -> None:
    settings.group = declare_app_settings(
        "public",
        defs=[
            SettingDef(
                "featured_org_handle",
                "string",
                "",
                "Promoted org handle — serves its pages at /",
            ),
        ],
    )


async def _console_overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    handle: str = settings.featured_org_handle  # type: ignore[assignment]
    lines = [f"Promoted: {handle}"] if handle else ["Nothing to report yet"]
    return ConsoleOverview(key="public", title="Public site", icon="globe", data={"lines": lines})
