"""The timeline's mount. It also owns the log settings ``apps/shared/logs`` applies."""

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
# Nothing writes below INFO. The level gates the log sink only, never facts or occurrences.
LOG_LEVELS = ("INFO", "WARNING", "ERROR")
DEFAULT_LOG_LEVEL = "INFO"

HEAVY_QUERIES_KEY = "heavy_request_queries"
HEAVY_MS_KEY = "heavy_request_ms"

PURGE_TOPIC = "timeline.purge"
PURGE_EVERY_SECONDS = 86400


def mount(host: Host) -> None:
    settings = host.register_settings(_declare_settings())
    # Before the enabled gate: the settings screen offers them while the app is off.
    cast("dict[str, object]", templates.env.globals)["log_levels"] = lambda: LOG_LEVELS
    if not settings.enabled:
        return
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
    """Push the settings onto ``apps/shared``, which may not read a feature's settings."""
    apply_log_level(level)
    apply_heavy_request_thresholds(queries=queries, ms=ms)


async def _reload_observability(event: SettingsChanged) -> None:
    """Reads the event's values, not the handle, which may not have reloaded yet."""
    if event.target_app != TIMELINE_APP:
        return
    _apply_observability(
        level=str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL),
        queries=int(event.values.get(HEAVY_QUERIES_KEY) or DEFAULT_HEAVY_QUERIES),
        ms=int(event.values.get(HEAVY_MS_KEY) or DEFAULT_HEAVY_MS),
    )


async def _purge(session: AsyncSession, _payload: dict) -> None:
    """Recurring retention of ``log_lines``."""
    retention = int(get_settings(TIMELINE_APP).retention_days)
    await LogRepository(session).purge(retention_days=retention)


async def _plant_purge() -> None:
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception as exc:
        log.warning("timeline.plant_purge_failed", exc_info=exc)


async def _overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The console tile; business events are one of its sources, with no screen of their own."""
    return ConsoleOverview(
        key=TIMELINE_APP,
        title="Timeline",
        icon="scroll",
        section="operations",
        data={"lines": [f"log level {get_settings(TIMELINE_APP).log_level}"]},
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
                "Log level for structlog and stdlib — applies live, no restart",
            ),
            SettingDef("retention_days", "number", "30", "Days of log lines to keep"),
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
