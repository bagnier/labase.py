"""How the issues context (error tracking) plugs into the running app.

Subscribes to shared's ``ExceptionCaptured`` (500 handler + event-bus failures),
groups events by stack fingerprint, and serves the console screen. Audit
doctrine verbatim: persistence is best-effort through collect()'s log-and-skip
semantics — a failing tracker never worsens the failure it is tracking.

NOTE: mounted BEFORE the console context so its /console/issues routes register
ahead of the console's /console/{app} catch-all.
"""

import structlog

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.issues.contract.events import IssueOpened, IssueRegressed
from apps.issues.domain import service
from apps.issues.infra.repository import (
    ErrorGroupRepository,
    purge_old_events,
    record_event,
)
from apps.issues.infra.router import router
from apps.shared.bus import bus
from apps.shared.config import get_technical_settings
from apps.shared.email import Email, enqueue_email
from apps.shared.host import Host, MountPhase
from apps.shared.observability.capture import CaptureDrain
from apps.shared.observability.errors import ExceptionCaptured
from apps.shared.persistence.database import admin_session_factory
from apps.shared.queue import ensure_scheduled, register_task_handler
from apps.shared.settings import (
    SettingDef,
    SettingsDeclaration,
    SupabaseLink,
    feature_switch,
    get_settings,
)

PHASE = MountPhase.CONSOLE_SCREEN

log = structlog.get_logger("labase.issues")

PURGE_TOPIC = "issues.purge"
PURGE_EVERY_SECONDS = 86400
# How often the capture queue is drained into error groups — near-real-time, cheap.
CAPTURE_DRAIN_SECONDS = 1.0


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    host.app.include_router(router, prefix="/console/issues")
    host.events.on(ExceptionCaptured, _record)
    host.events.on(IssueOpened, _alert_opened)
    host.events.on(IssueRegressed, _alert_regressed)
    register_task_handler(PURGE_TOPIC, _purge)
    host.on_startup(_plant_purge)
    # Every ``log.exception`` is queued by the capture processor; this drains it into groups.
    drain = CaptureDrain(CAPTURE_DRAIN_SECONDS)
    host.on_startup(drain.start)
    host.on_shutdown(drain.stop)


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="issues",
        defs=[
            feature_switch(),
            SettingDef("retention_days", "number", "30", "Days of error events to keep"),
            SettingDef("alerting_enabled", "boolean", "false", "Email on new/regressed issues"),
            SettingDef("alert_email", "string", "", "Where issue alerts are sent"),
        ],
        supabase=SupabaseLink("Browse error groups in Supabase", table="error_groups"),
    )


async def _record(event: ExceptionCaptured) -> None:
    """Fold a captured exception into its group; runs under collect(): best-effort."""
    version = get_technical_settings().app_version
    context = {
        **event.context,
        "source": event.source,
        "stack": service.formatted_stack(event.exc),
    }
    async with admin_session_factory()() as session:
        recorded = await record_event(
            session,
            fingerprint=service.fingerprint(event.exc),
            title=service.title_for(event.exc),
            version=version,
            context=context,
        )
        group_id, title, resolved_in = (
            recorded.group.id,
            recorded.group.title,
            recorded.group.resolved_in_version,
        )
        await session.commit()
    log.info("issue.recorded", group_id=group_id, opened=recorded.opened)
    # ``_record`` is only subscribed when the app is enabled (see ``mount``), so reaching the
    # bus here is unconditional — no mount-state guard needed.
    if recorded.opened:
        await bus.emit(IssueOpened(group_id=group_id, title=title))
    if recorded.regressed:
        await bus.emit(
            IssueRegressed(
                group_id=group_id,
                title=title,
                resolved_in_version=resolved_in,
                seen_version=version,
            )
        )


async def _alert_opened(event: IssueOpened) -> None:
    await _send_alert(f"New issue: {event.title}", event.group_id)


async def _alert_regressed(event: IssueRegressed) -> None:
    await _send_alert(f"Regressed issue: {event.title}", event.group_id)


async def _send_alert(subject: str, group_id: int) -> None:
    settings = get_settings("issues")
    if not settings.alerting_enabled or not settings.alert_email:
        return
    text = f"{subject}\n\nSee /console/issues/{group_id} for the stack and context."
    email = Email(to=str(settings.alert_email), subject=subject, text=text)
    try:  # alerting is best-effort: a failing enqueue never worsens the tracked failure
        async with admin_session_factory()() as session:
            await enqueue_email(session, email)
            await session.commit()
    except Exception:
        log.warning("issues.alert_enqueue_failed", group_id=group_id)


async def _purge(session, _payload: dict) -> None:
    deleted = await purge_old_events(session, int(get_settings("issues").retention_days))
    log.info("issues.purged", deleted=deleted)


async def _plant_purge() -> None:
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception:
        log.warning("issues.plant_purge_failed")


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    unresolved = await ErrorGroupRepository(query.session).unresolved_count()
    lines = [f"{unresolved} unresolved"] if unresolved else ["No open issues"]
    return ConsoleOverview(
        key="issues", title="Issues", icon="bug-beetle", section="operations", data={"lines": lines}
    )
