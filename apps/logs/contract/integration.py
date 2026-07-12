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
from apps.logs.contract.queries import org_activity
from apps.logs.infra.events_router import events_router
from apps.logs.infra.router import router
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.shared import clock
from apps.shared.charts import day_buckets_series
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
    host.events.on(SettingsChanged, _reload_level)
    host.events.on(ConsoleOverviewQuery, _overview)
    host.events.on(ConsoleOverviewQuery, _events_overview)
    host.events.on(OverviewQuery, _org_overview)
    host.app.include_router(router, prefix="/console/logs")
    # A fixed /console/events screen — registered in this CONSOLE_SCREEN phase, ahead of the
    # console's /console/{app} catch-all, exactly like /console/logs above.
    host.app.include_router(events_router, prefix="/console/events")


async def _reload_level(event: SettingsChanged) -> None:
    """Re-point the live loggers when the logs app's level is edited (self-contained: reads the
    event's own values, independent of registry-reload ordering on the bus)."""
    if event.app_name == LOGS_APP:
        apply_log_level(str(event.values.get(LOG_LEVEL_KEY) or DEFAULT_LOG_LEVEL))


_ACTIVITY_DAYS = 14
_SOURCE_NAMES = {"request": "Requests", "event": "Events", "issue": "Errors"}


async def _org_overview(query: OverviewQuery) -> Overview:
    """The org dashboard's activity graph — logs' one member-facing contribution.

    Aggregates only (see :func:`org_activity`); the card spans the dashboard grid and
    disappears with the app, like any other overview."""
    buckets = await org_activity(query.org_id, days=_ACTIVITY_DAYS)
    config = day_buckets_series(
        buckets, days=_ACTIVITY_DAYS, end=clock.now().date(), names=_SOURCE_NAMES
    )
    return Overview(
        key="activity",
        title=f"Activity — last {_ACTIVITY_DAYS} days",
        icon="pulse",
        href="dashboard",
        template="logs/_org_activity.html",
        data={"config": config, "active": bool(buckets)},
    )


async def _overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The consolidated logs tile on the console grid — the single observability entry point."""
    return ConsoleOverview(
        key=LOGS_APP,
        title="Logs",
        icon="scroll",
        section="operations",
        data={"lines": [f"firehose level {get_settings(LOGS_APP).log_level}"]},
    )


async def _events_overview(_query: ConsoleOverviewQuery) -> ConsoleOverview:
    """The business-events tile — the per-app timeline of every app's typed events."""
    return ConsoleOverview(
        key="events",
        title="Business events",
        icon="broadcast",
        section="operations",
        href="/console/events",
        data={"lines": ["every app's typed events, grouped per app"]},
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
