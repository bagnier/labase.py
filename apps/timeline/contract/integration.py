"""How the timeline context plugs into the running app.

``apps/timeline`` is the single observability *read* context: it merges the firehose (a rotated
JSON file), the business-events journal (``business_events``) and issue occurrences
(``issue_occurrences``) into one admin-only timeline, with an activity graph and structured export.
The *write* primitives stay in ``apps/shared/observability`` — a foundation every app imports down.

NOTE: mounted BEFORE the console context so its /console/timeline routes register ahead of the
console's /console/{app} catch-all.
"""

import structlog

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
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
from apps.timeline.infra.router import router

PHASE = MountPhase.CONSOLE_SCREEN

log = structlog.get_logger("labase.timeline")

TIMELINE_APP = "timeline"
LOG_LEVEL_KEY = "log_level"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
# The firehose defaults to WARNING — quiet enough that request/app diagnostics don't drown the
# business and issue signal — and an admin can lower it live from the timeline when they need
# the detail. The other two sources never depend on this level (each has its own write path).
DEFAULT_LOG_LEVEL = "WARNING"


def mount(host: Host) -> None:
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    # Align the live process with the persisted level at mount, then keep it in step as the
    # console edits it.
    apply_log_level(str(settings.log_level))
    host.events.spread(SettingsChanged, _reload_level)
    host.contribs.provide(ConsoleOverviewQuery, _overview)
    host.app.include_router(router, prefix="/console/timeline")


async def _reload_level(event: SettingsChanged) -> None:
    """Re-point the live loggers when this app's firehose level is edited (self-contained: reads
    the event's own values, independent of registry-reload ordering on the bus)."""
    if event.target_app == TIMELINE_APP:
        apply_log_level(str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL))


async def _overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The consolidated timeline tile on the console grid — the single observability entry point.

    Business events are one source *inside* it (filter by source ``business``, narrow by app,
    correlate by entity), so there is no separate business-events screen to link out to."""
    return ConsoleOverview(
        key=TIMELINE_APP,
        title="Timeline",
        icon="scroll",
        section="operations",
        data={"lines": [f"firehose level {get_settings(TIMELINE_APP).log_level}"]},
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name=TIMELINE_APP,
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
