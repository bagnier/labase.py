"""The metrics mount (AGENTS: load metrics belong to their app alone): a Prometheus endpoint, a
per-process flusher of per-minute deltas, the console Load screen, and a daily rollup from minute
to hour rows with retention.
"""

from datetime import timedelta

import structlog

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.metrics.domain.accumulator import accumulator
from apps.metrics.infra.flusher import MetricsFlusher
from apps.metrics.infra.repository import purge, rollup, total_requests
from apps.metrics.infra.router import WINDOW_HOURS, exposition_router, router
from apps.shared import clock
from apps.shared.integration.host import Host, MountPhase
from apps.shared.logs.request import on_request_measured
from apps.shared.queue import ensure_scheduled, register_task_handler
from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import (
    SettingDef,
    SettingsDeclaration,
    SupabaseLink,
    feature_switch,
    get_settings,
)

PHASE = MountPhase.CONSOLE_SCREEN

log = structlog.get_logger(__name__)

ROLLUP_TOPIC = "metrics.rollup"
ROLLUP_EVERY_SECONDS = 86400
MINUTE_RETENTION_DAYS = 7


def mount(host: Host) -> None:
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    host.reserve("metrics")
    if not settings.enabled:
        return
    # Behind the gate: switched off, nothing counts.
    on_request_measured(accumulator.observe)
    host.app.include_router(exposition_router)
    host.app.include_router(router, prefix="/console/load")
    register_task_handler(ROLLUP_TOPIC, _rollup)
    host.on_startup(_plant_rollup)
    flusher = MetricsFlusher(get_technical_settings().metrics_flush_seconds)
    host.run_background(flusher)


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
    await rollup(session, minute_retention_days=MINUTE_RETENTION_DAYS)
    await purge(session, int(get_settings("metrics").retention_days))


async def _plant_rollup() -> None:
    try:
        await ensure_scheduled(ROLLUP_TOPIC, ROLLUP_EVERY_SECONDS)
    except Exception as exc:
        log.warning("metrics.plant_rollup_failed", exc_info=exc)


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
