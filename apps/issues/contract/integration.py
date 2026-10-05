"""The issues mount: a capture tracker folding each ``log.exception`` into an issue by stack
fingerprint (AGENTS: a bug is an issue with a lifecycle), and the console screen.
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
from apps.shared.email import Email, enqueue_email
from apps.shared.events.bus import events
from apps.shared.integration.host import Host, MountPhase
from apps.shared.logs.capture import CaptureDrain, ExceptionCaptured, on_captured
from apps.shared.persistence.database import admin_session_factory
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

PURGE_TOPIC = "issues.purge"
PURGE_EVERY_SECONDS = 86400
CAPTURE_DRAIN_SECONDS = 1.0


def mount(host: Host) -> None:
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    if not settings.enabled:
        return
    host.app.include_router(router, prefix="/console/issues")
    on_captured(_track)
    host.events.declare(IssueOpened, IssueRegressed, IssueStatusChanged)
    # (AGENTS: an app may subscribe to its own business event)
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
    """The failing request's ids from the captured context, to bind for the fact: the drain's
    task has no request of its own. Never the actor, or the issue would show in their feed.
    """
    return {k: str(v) for k in ("request_id", "request_name") if (v := context.get(k)) is not None}


async def _track(captured: ExceptionCaptured) -> None:
    """Fold the exception into its issue; its opening or regression fact shares the transaction."""
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


async def _alert_opened(session: AsyncSession, event: IssueOpened) -> None:
    await _send_alert(session, f"New issue: {event.entity_name}", event.entity_id)


async def _alert_regressed(session: AsyncSession, event: IssueRegressed) -> None:
    await _send_alert(session, f"Regressed issue: {event.entity_name}", event.entity_id)


async def _send_alert(session: AsyncSession, subject: str, issue_id: uuid.UUID) -> None:
    settings = get_settings("issues")
    if not settings.alerting_enabled or not settings.alert_email:
        return
    text = f"{subject}\n\nSee /console/issues/{issue_id} for the stack and context."
    email = Email(to=str(settings.alert_email), subject=subject, text=text)
    try:  # best effort: must not worsen the failure it reports
        await enqueue_email(session, email)
    except Exception as exc:
        log.warning("issues.alert_enqueue_failed", issue_id=str(issue_id), exc_info=exc)


async def _purge(session: AsyncSession, _payload: dict) -> None:
    await purge_old_occurrences(session, int(get_settings("issues").retention_days))


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
