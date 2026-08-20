"""How the timeline context plugs into the running app.

``apps/timeline`` is the single observability *read* context: it merges the firehose (a rotated
JSON file), the business-events journal (``business_events``) and issue occurrences
(``issue_occurrences``) into one admin-only timeline, with an activity graph and structured export.
The *write* primitives stay in ``apps/shared/observability`` — a foundation every app imports down.

NOTE: mounted BEFORE the console context so its /console/timeline routes register ahead of the
console's /console/{app} catch-all.
"""

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.host import Host, MountPhase
from apps.shared.observability.logging import apply_log_level
from apps.shared.observability.repository import LogRepository
from apps.shared.queue import ensure_scheduled, register_task_handler
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

log = structlog.get_logger(__name__)

TIMELINE_APP = "timeline"
LOG_LEVEL_KEY = "log_level"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
# The firehose defaults to INFO, so every technical fact the code states is actually recorded —
# a served request, a drained task, an occurrence folded into its issue. At WARNING those lines
# were written in the code and dropped by the filter, which made the timeline's `logs` source
# empty on a healthy server: only failures had ever happened. An admin can still raise the level
# to quiet a noisy instance, or lower it to DEBUG for per-query traces. The other two sources
# never depend on this level (each has its own write path).
DEFAULT_LOG_LEVEL = "INFO"

PURGE_TOPIC = "timeline.purge"
PURGE_EVERY_SECONDS = 86400


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
    register_task_handler(PURGE_TOPIC, _purge)
    host.on_startup(_plant_purge)


async def _reload_level(event: SettingsChanged) -> None:
    """Re-point the live loggers when this app's firehose level is edited (self-contained: reads
    the event's own values, independent of registry-reload ordering on the bus)."""
    if event.target_app == TIMELINE_APP:
        apply_log_level(str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL))


async def _purge(session: AsyncSession, _payload: dict) -> None:
    """Retention consumer. The firehose is one row per line, so this is the counterweight that
    makes a table viable where ``request_metrics`` uses aggregation instead — and the delete the
    per-day files promised ("retention is a plain file delete") and never performed."""
    retention = int(get_settings(TIMELINE_APP).retention_days)
    deleted = await LogRepository(session).purge(retention_days=retention)
    log.info("timeline.purged", deleted=deleted)


async def _plant_purge() -> None:
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception as exc:
        log.warning("timeline.plant_purge_failed", exc_info=exc)


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
            SettingDef("retention_days", "number", "30", "Days of firehose lines to keep"),
        ],
        supabase=SupabaseLink("Browse the log lines in Supabase", table="log_lines"),
    )
