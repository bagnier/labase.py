"""Runtime log-level control — a declared console setting applied live.

The console edits ``observability.log_level`` on the Settings page; the change
converges like any setting: instantly on the emitting instance
(``SettingsChanged``), within one TTL elsewhere (``SettingsRefresher``). No
redeploy, no env edit.
"""

from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    AppSettings,
    SettingDef,
    SettingsChanged,
    declare_app_settings,
)
from apps.shared.observability.logging import apply_log_level, default_log_level

OBSERVABILITY_APP = "observability"
LOG_LEVEL_KEY = "log_level"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

observability = AppSettings(OBSERVABILITY_APP)


def declare() -> None:
    """Declare the group, then align the process with the persisted level (mount-time)."""
    observability.group = declare_app_settings(
        OBSERVABILITY_APP,
        defs=[
            SettingDef(
                LOG_LEVEL_KEY,
                "string",
                default_log_level(),
                "Log level for structlog and stdlib — applies live, no restart",
            )
        ],
    )
    observability.read()
    apply_log_level(str(observability.log_level))


async def reload(event: SettingsChanged) -> None:
    """Console event handler: adopt fresh values and re-point the loggers."""
    await observability.reload(event)
    if event.app == OBSERVABILITY_APP:
        apply_log_level(str(observability.log_level))


async def overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    return ConsoleOverview(
        key=OBSERVABILITY_APP,
        title="Logging",
        icon="terminal-window",
        group="settings",
        data={"lines": [f"level {observability.log_level}"]},
    )
