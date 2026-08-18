"""How the metrics context (load metrics) plugs into the running app.

Layer 1: the shared accumulator (fed by ``RequestLogger``) is exposed as a
Prometheus endpoint. Layer 2: a per-process flusher persists per-minute deltas
and the console "Load" screen aggregates them; a daily rollup downsamples
minute → hour and applies retention (async-substrate consumer, like
``issues.purge``).

NOTE: mounted BEFORE the console context so its /console/load routes register
ahead of the console's /console/{app} catch-all.
"""

from datetime import timedelta

import structlog

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.metrics.infra.flusher import MetricsFlusher
from apps.metrics.infra.repository import purge, rollup, total_requests
from apps.metrics.infra.router import WINDOW_HOURS, exposition_router, router
from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.host import Host, MountPhase
from apps.shared.queue import ensure_scheduled, register_task_handler
from apps.shared.settings import (
    SettingDef,
    SettingsDeclaration,
    SupabaseLink,
    feature_switch,
    get_settings,
)

PHASE = MountPhase.CONSOLE_SCREEN

log = structlog.get_logger("labase.metrics")

ROLLUP_TOPIC = "metrics.rollup"
ROLLUP_EVERY_SECONDS = 86400
MINUTE_RETENTION_DAYS = 7


def mount(host: Host) -> None:
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    host.reserve("metrics")
    if not settings.enabled:
        return
    host.app.include_router(exposition_router)
    host.app.include_router(router, prefix="/console/load")
    register_task_handler(ROLLUP_TOPIC, _rollup)
    host.on_startup(_plant_rollup)
    flusher = MetricsFlusher(get_technical_settings().metrics_flush_seconds)
    host.on_startup(flusher.start)
    host.on_shutdown(flusher.stop)


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="metrics",
        defs=[
            feature_switch(),
            SettingDef("retention_days", "number", "30", "Days of hourly metrics to keep"),
        ],
        supabase=SupabaseLink("Browse raw metrics in Supabase", table="request_metrics"),
    )


async def _rollup(session, _payload: dict) -> None:
    removed, merged = await rollup(session, minute_retention_days=MINUTE_RETENTION_DAYS)
    purged = await purge(session, int(get_settings("metrics").retention_days))
    log.info("metrics.rolled_up", minute_rows=removed, hour_rows=merged, purged=purged)


async def _plant_rollup() -> None:
    try:
        await ensure_scheduled(ROLLUP_TOPIC, ROLLUP_EVERY_SECONDS)
    except Exception:
        log.warning("metrics.plant_rollup_failed")


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    since = clock.now() - timedelta(hours=WINDOW_HOURS)
    total = await total_requests(query.session, since)
    lines = [f"{total} requests ({WINDOW_HOURS}h)"] if total else ["No traffic yet"]
    return ConsoleOverview(
        key="metrics",
        title="Load",
        icon="gauge",
        section="operations",
        href="/console/load",
        data={"lines": lines},
    )
