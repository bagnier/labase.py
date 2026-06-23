"""How the public context plugs into the running app: mounts the landing-page router."""

from fastapi import FastAPI

from apps.public.infra.router import router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import declare_app_settings
from apps.shared.host import Host


def mount(app: FastAPI, host: Host) -> None:
    app.include_router(router)
    host.events.on(ConsoleOverviewQuery, _console_overview)
    declare_app_settings("public", defs=[])


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    # The public site has no server-wide metrics yet — the card is wired for when it does.
    return ConsoleOverview(
        key="public", title="Public site", icon="globe", data={"lines": ["Nothing to report yet"]}
    )
