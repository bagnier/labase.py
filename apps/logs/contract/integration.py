"""How the logs context plugs into the running app.

``apps/logs`` is the single observability *read* context: it merges the firehose (a rotated
JSON file), the business-events trail (``business_events``) and issue occurrences
(``error_events``) into one admin-only timeline, with an activity graph and structured export.
The *write* primitives stay in ``apps/shared/observability`` — a foundation every app imports down.

NOTE: mounted BEFORE the console context so its /console/logs routes register ahead of the
console's /console/{app} catch-all.
"""

import structlog

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.logs.infra.router import router
from apps.shared.host import Host, MountPhase
from apps.shared.observability.logging import apply_log_level
from apps.shared.settings import (
    SettingDef,
    SettingsChanged,
    SettingsDeclaration,
    SupabaseLink,
    feature_switch,
    get_settings,
)

PHASE = MountPhase.CONSOLE_SCREEN

log = structlog.get_logger("labase.logs")

LOGS_APP = "logs"
LOG_LEVEL_KEY = "log_level"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
# The firehose defaults to WARNING — quiet enough that request/app diagnostics don't drown the
# event and issue signal — and an admin can lower it live from the logs screen when they need
# the detail. Event and issue contributions never depend on this level (own persistence path).
DEFAULT_LOG_LEVEL = "WARNING"


def mount(host: Host) -> None:
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    # Align the live process with the persisted level at mount, then keep it in step as the
    # console edits it — the observability control the console used to own now lives with the
    # screen that reads the logs.
    apply_log_level(str(settings.log_level))
    host.events.spread(SettingsChanged, _reload_level)
    host.contribs.provide(ConsoleOverviewQuery, _overview)
    host.app.include_router(router, prefix="/console/logs")


async def _reload_level(event: SettingsChanged) -> None:
    """Re-point the live loggers when the logs app's level is edited (self-contained: reads the
    event's own values, independent of registry-reload ordering on the bus)."""
    if event.app_name == LOGS_APP:
        apply_log_level(str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL))


async def _overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The consolidated logs tile on the console grid — the single observability entry point.

    Business events are one source *inside* the logs viewer (filter by source ``event``, narrow by
    app, correlate by entity), so there's no separate business-events screen to link out to."""
    return ConsoleOverview(
        key=LOGS_APP,
        title="Logs",
        icon="scroll",
        section="operations",
        data={"lines": [f"firehose level {get_settings(LOGS_APP).log_level}"]},
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name=LOGS_APP,
        defs=[
            feature_switch(),
            SettingDef(
                LOG_LEVEL_KEY,
                "string",
                DEFAULT_LOG_LEVEL,
                "Firehose log level for structlog and stdlib — applies live, no restart",
            ),
        ],
        supabase=SupabaseLink("Browse the business events in Supabase", table="business_events"),
    )
