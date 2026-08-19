"""How the issues context plugs into the running app.

Registers a tracker with the capture module — which hands it every ``log.exception``, whatever
raised it — folds each one into an issue by stack fingerprint, and serves the console screen.
The drain fans out with log-and-skip isolation, so a failing tracker never worsens the failure
it is tracking.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import bound_contextvars

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.issues.contract.events import IssueOpened, IssueRegressed, IssueStatusChanged
from apps.issues.domain import service
from apps.issues.infra.repository import (
    IssueRepository,
    purge_old_occurrences,
    see_occurrence,
)
from apps.issues.infra.router import router
from apps.shared.config import get_technical_settings
from apps.shared.email import Email, enqueue_email
from apps.shared.events.bus import events
from apps.shared.host import Host, MountPhase
from apps.shared.observability.capture import CaptureDrain, ExceptionCaptured, on_captured
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

log = structlog.get_logger(__name__)

PURGE_TOPIC = "issues.purge"
PURGE_EVERY_SECONDS = 86400
# How often the capture queue is drained into issues — near-real-time, and cheap.
CAPTURE_DRAIN_SECONDS = 1.0


def mount(host: Host) -> None:
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    host.app.include_router(router, prefix="/console/issues")
    on_captured(_track)  # exception capture is delivered off the bus, observability → issues
    host.events.declare(IssueOpened, IssueRegressed, IssueStatusChanged)
    host.events.on(IssueOpened, _alert_opened, name="alert_opened", app="issues")
    host.events.on(IssueRegressed, _alert_regressed, name="alert_regressed", app="issues")
    register_task_handler(PURGE_TOPIC, _purge)
    host.on_startup(_plant_purge)
    host.run_background(CaptureDrain(CAPTURE_DRAIN_SECONDS))


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="issues",
        defs=[
            feature_switch(),
            SettingDef("retention_days", "number", "30", "Days of occurrences to keep"),
            SettingDef("alerting_enabled", "boolean", "false", "Email on new/regressed issues"),
            SettingDef("alert_email", "string", "", "Where issue alerts are sent"),
        ],
        supabase=SupabaseLink("Browse the issues in Supabase", table="issues"),
    )


def _originating_request(context: dict[str, Any]) -> dict[str, str]:
    """The request the exception escaped, read back off the captured context.

    The journal's write path takes these from contextvars, and ``_track`` runs on the drain's own
    task — no request, no contextvars — so a fact recorded here named no request at all, and
    correlating a timeline by request showed the log line and the occurrence but never the
    "this issue just opened" that explains them. The capture processor snapshotted them at the
    moment of the failure; this hands them back.

    Only the request, never the actor: ``business_events`` is RLS-readable by the user it names
    and the profile feed renders it, so attributing an internal issue to whoever happened to trip
    it would file it in *their* activity. These facts stay server-wide (see ``contract.events``).
    """
    return {k: str(v) for k in ("request_id", "request_name") if (v := context.get(k)) is not None}


async def _track(captured: ExceptionCaptured) -> None:
    """Fold a captured exception into its issue, and record the fact that opens or reopens it on
    the very same transaction — so the fact lands iff the occurrence does."""
    version = get_technical_settings().app_version
    context = {**captured.context, "stack": service.formatted_stack(captured.exc)}
    async with admin_session_factory()() as session:
        seen = await see_occurrence(
            session,
            fingerprint=service.fingerprint(captured.exc),
            title=service.title_for(captured.exc),
            version=version,
            context=context,
        )
        issue_id, title = seen.issue.id, seen.issue.title
        # ``_track`` is only subscribed when the app is enabled (see ``mount``), so reaching the
        # bus here is unconditional — no mount-state guard needed.
        with bound_contextvars(**_originating_request(captured.context)):
            if seen.opened:
                await events.emit(IssueOpened(entity_id=issue_id, entity_name=title), session)
            if seen.regressed:
                await events.emit(
                    IssueRegressed(
                        entity_id=issue_id,
                        entity_name=title,
                        resolved_in_release=seen.issue.resolved_in_release,
                        seen_version=version,
                    ),
                    session,
                )
        await session.commit()
    log.info("issues.occurrence_recorded", issue_id=str(issue_id), opened=seen.opened)


async def _alert_opened(session: AsyncSession, event: IssueOpened) -> None:
    await _send_alert(session, f"New issue: {event.entity_name}", event.entity_id)


async def _alert_regressed(session: AsyncSession, event: IssueRegressed) -> None:
    await _send_alert(session, f"Regressed issue: {event.entity_name}", event.entity_id)


async def _send_alert(session: AsyncSession, subject: str, issue_id: uuid.UUID) -> None:
    # Durable consumer: the alert email is enqueued on the worker's session (it commits).
    settings = get_settings("issues")
    if not settings.alerting_enabled or not settings.alert_email:
        return
    text = f"{subject}\n\nSee /console/issues/{issue_id} for the stack and context."
    email = Email(to=str(settings.alert_email), subject=subject, text=text)
    try:  # alerting is best-effort: a failing enqueue never worsens the tracked failure
        await enqueue_email(session, email)
    except Exception as exc:
        log.warning("issues.alert_enqueue_failed", issue_id=str(issue_id), exc_info=exc)


async def _purge(session: AsyncSession, _payload: dict) -> None:
    deleted = await purge_old_occurrences(session, int(get_settings("issues").retention_days))
    log.info("issues.purged", deleted=deleted)


async def _plant_purge() -> None:
    try:
        await ensure_scheduled(PURGE_TOPIC, PURGE_EVERY_SECONDS)
    except Exception as exc:
        log.warning("issues.plant_purge_failed", exc_info=exc)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    unresolved = await IssueRepository(query.session).unresolved_count()
    lines = [f"{unresolved} unresolved"] if unresolved else ["No open issues"]
    return ConsoleOverview(
        key="issues", title="Issues", icon="bug-beetle", section="operations", data={"lines": lines}
    )
