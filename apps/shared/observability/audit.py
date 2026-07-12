"""Best-effort audit shim over the business-events store — being withdrawn.

Historically its own append-only trail; now a thin writer in front of
:mod:`apps.shared.observability.business_events`. Each ``audit()`` call site is being migrated
to emit a typed :class:`~apps.shared.events.BusinessEvent` on the bus (which the store's
persister records); until the last site moves, ``audit()`` keeps the trail complete by writing
to the SAME ``business_events`` table — its ``event`` string is the event ``kind``.

Best-effort by doctrine (README): logged immediately, then persisted after the response via the
request ``BackgroundTasks`` — a lost write never blocks or fails the mutation.
"""

import uuid
from typing import Any

import structlog
from fastapi import BackgroundTasks
from structlog.contextvars import get_contextvars

from apps.shared.observability.business_events import insert_business_event

log = structlog.get_logger("labase.audit")


async def _insert_audit_log(
    level: str,
    event: str,
    user_id: str | None,
    ip: str | None,
    org_id: str | None,
    request_id: str | None,
    payload: dict[str, Any],
) -> None:
    """Positional writer kept for existing call sites/tests — delegates to the store."""
    await insert_business_event(
        kind=event,
        level=level,
        user_id=user_id,
        ip=ip,
        org_id=org_id,
        request_id=request_id,
        payload=payload or None,
    )


def _record_audit_event(
    bg: BackgroundTasks,
    *,
    level: str,
    event: str,
    user_id: str | None = None,
    ip: str | None = None,
    org_id: str | None = None,
    request_id: str | None = None,
    **payload: Any,
) -> None:
    log.info(event, level=level, user_id=user_id, ip=ip, org_id=org_id, **payload)
    bg.add_task(_insert_audit_log, level, event, user_id, ip, org_id, request_id, payload)


def audit(
    bg: BackgroundTasks,
    event: str,
    *,
    level: str = "info",
    user_id: str | uuid.UUID | None = None,
    org_id: str | uuid.UUID | None = None,
    ip: str | None = None,
    **fields: Any,
) -> None:
    """Record a sensitive action: logged now, persisted after the response via ``bg`` (the
    request's ``BackgroundTasks``), so the write never delays the mutation.

    ``org_id`` and the request's ``request_id`` (from the structlog contextvars bound by
    ``RequestLogger``) are persisted as first-class columns.
    """
    _record_audit_event(
        bg,
        level=level,
        event=event,
        user_id=str(user_id) if user_id is not None else None,
        ip=ip,
        org_id=str(org_id) if org_id is not None else None,
        request_id=get_contextvars().get("request_id"),
        **fields,
    )
