"""How the public context plugs into the running app: mounts the landing-page router."""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.public.infra.router import router
from apps.shared.host import Host, MountPhase
from apps.shared.settings import SettingDef, SettingsDeclaration, get_settings

PHASE = MountPhase.PUBLIC


def mount(host: Host) -> None:
    host.register_settings(_declare_settings())
    host.app.include_router(router)
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="public",
        defs=[
            SettingDef(
                "featured_org_handle",
                "string",
                "",
                "Promoted org handle — serves its pages at /",
                org_overridable=False,
            ),
        ],
    )


async def _console_overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    handle: str = get_settings("public").featured_org_handle  # type: ignore[assignment]
    lines = [f"Promoted: {handle}"] if handle else ["Nothing to report yet"]
    return ConsoleOverview(
        key="public",
        title="Public site",
        icon="globe",
        section="configuration",
        data={"lines": lines},
    )
