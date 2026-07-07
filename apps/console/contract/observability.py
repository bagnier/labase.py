"""Runtime log-level control — a declared console setting applied live.

The console edits ``observability.log_level`` on the Settings page; the change
converges like any setting: instantly on the emitting instance
(``SettingsChanged``), within one TTL elsewhere (``SettingsRefresher``). No
redeploy, no env edit.
"""

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.host import Host
from apps.shared.observability.logging import apply_log_level, default_log_level
from apps.shared.settings import SettingDef, SettingsChanged, SettingsDeclaration, get_settings

OBSERVABILITY_APP = "observability"
LOG_LEVEL_KEY = "log_level"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")


def declare(host: Host) -> None:
    """Declare the group, then align the process with the persisted level (mount-time)."""
    settings = host.register_settings(
        SettingsDeclaration(
            app_name=OBSERVABILITY_APP,
            defs=[
                SettingDef(
                    LOG_LEVEL_KEY,
                    "string",
                    default_log_level(),
                    "Log level for structlog and stdlib — applies live, no restart",
                )
            ],
        )
    )
    apply_log_level(str(settings.log_level))
    # register_settings already keeps the registry handle current; this second subscription
    # reacts to the change with the one extra step logging needs: re-pointing the live loggers.
    host.events.on(SettingsChanged, reload)


async def reload(event: SettingsChanged) -> None:
    """Console event handler: re-point the loggers at the freshly edited level.

    Reads the event's own values — self-contained, no dependence on the registry
    handle having been reloaded first (handler order on the bus)."""
    if event.app_name == OBSERVABILITY_APP:
        apply_log_level(str(event.values.get(LOG_LEVEL_KEY) or default_log_level()))


async def overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    return ConsoleOverview(
        key=OBSERVABILITY_APP,
        title="Logging",
        icon="terminal-window",
        group="settings",
        data={"lines": [f"level {get_settings(OBSERVABILITY_APP).log_level}"]},
    )
