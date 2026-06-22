"""How the public context plugs into the running app: mounts the landing-page router."""

from fastapi import FastAPI

from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import ConsoleSettingsQuery, SettingsGroup
from app.public.infra.router import router
from app.shared.host import Host


def mount(app: FastAPI, host: Host) -> None:
    app.include_router(router)
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.events.on(ConsoleSettingsQuery, _console_settings)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    # The public site has no server-wide metrics yet — the card is wired for when it does.
    return ConsoleOverview(
        key="public", title="Public site", icon="globe", data={"lines": ["Nothing to report yet"]}
    )


async def _console_settings(query: ConsoleSettingsQuery) -> SettingsGroup:
    return SettingsGroup(app="public")
