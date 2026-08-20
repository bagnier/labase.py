"""How the timeline context plugs into the running app.

``apps/timeline`` is the single observability *read* context: it merges the log sink
(``log_lines``), the business-events journal (``business_events``) and issue occurrences
(``issue_occurrences``) into one admin-only timeline, with an activity graph and structured export.
The *write* primitives stay in ``apps/shared/logs`` — a foundation every app imports down.

NOTE: mounted BEFORE the console context so its /console/timeline routes register ahead of the
console's /console/{app} catch-all.
"""

from typing import cast

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.http.templates import templates
from apps.shared.integration.host import Host, MountPhase
from apps.shared.logs.chain import apply_log_level
from apps.shared.logs.repository import LogRepository
from apps.shared.persistence.sql_stats import (
    DEFAULT_HEAVY_MS,
    DEFAULT_HEAVY_QUERIES,
    apply_heavy_request_thresholds,
)
from apps.shared.queue import ensure_scheduled, register_task_handler
from apps.shared.settings.live import (
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
# INFO is the floor, not a middle setting: nothing in the codebase writes below it, so the three
# levels are the whole scale. Raising it to WARNING quiets an instance down to what it could not
# carry through; ERROR leaves only the bugs. The other two sources never depend on this level
# (each has its own write path).
LOG_LEVELS = ("INFO", "WARNING", "ERROR")
DEFAULT_LOG_LEVEL = "INFO"

HEAVY_QUERIES_KEY = "heavy_request_queries"
HEAVY_MS_KEY = "heavy_request_ms"

PURGE_TOPIC = "timeline.purge"
PURGE_EVERY_SECONDS = 86400


def mount(host: Host) -> None:
    settings = host.register_settings(_declare_settings())
    # Before the enabled gate, like the console tile: the levels this app accepts are what the
    # settings screen offers, and that screen is reachable while the app is switched off.
    cast("dict[str, object]", templates.env.globals)["log_levels"] = lambda: LOG_LEVELS
    if not settings.enabled:
        return
    # Align the live process with the persisted level at mount, then keep it in step as the
    # console edits it.
    _apply_observability(
        level=str(settings.log_level),
        queries=int(settings.heavy_request_queries),
        ms=int(settings.heavy_request_ms),
    )
    host.events.spread(SettingsChanged, _reload_observability)
    host.contribs.provide(ConsoleOverviewQuery, _overview)
    host.app.include_router(router, prefix="/console/timeline")
    register_task_handler(PURGE_TOPIC, _purge)
    host.on_startup(_plant_purge)


def _apply_observability(*, level: str, queries: int, ms: int) -> None:
    """Push this app's settings down onto the write primitives in ``apps/shared``.

    Both travel the same way and for the same reason: ``apps/shared`` is a foundation, so it may
    not read a feature's settings by name — the feature that owns them tells it instead. What is
    tuned here is only *what gets recorded*; the three sources of the Timeline are read back
    regardless (a fact and an occurrence never depend on the level).
    """
    apply_log_level(level)
    apply_heavy_request_thresholds(queries=queries, ms=ms)


async def _reload_observability(event: SettingsChanged) -> None:
    """Re-point the live process when these settings are edited (self-contained: reads the event's
    own values, independent of registry-reload ordering on the bus)."""
    if event.target_app != TIMELINE_APP:
        return
    _apply_observability(
        level=str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL),
        queries=int(event.values.get(HEAVY_QUERIES_KEY) or DEFAULT_HEAVY_QUERIES),
        ms=int(event.values.get(HEAVY_MS_KEY) or DEFAULT_HEAVY_MS),
    )


async def _purge(session: AsyncSession, _payload: dict) -> None:
    """Retention consumer. The firehose is one row per line, so this is the counterweight that
    makes a table viable where ``request_metrics`` uses aggregation instead — and the delete the
    per-day files promised ("retention is a plain file delete") and never performed."""
    retention = int(get_settings(TIMELINE_APP).retention_days)
    await LogRepository(session).purge(retention_days=retention)


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
            SettingDef(
                HEAVY_QUERIES_KEY,
                "number",
                str(DEFAULT_HEAVY_QUERIES),
                "Queries above which a request names its slowest statements",
            ),
            SettingDef(
                HEAVY_MS_KEY,
                "number",
                str(DEFAULT_HEAVY_MS),
                "Milliseconds in the database above which it does the same",
            ),
        ],
        supabase=SupabaseLink("Browse the log lines in Supabase", table="log_lines"),
    )
