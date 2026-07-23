"""The business-events write path — ``emit``'s persistence of the append-only trail.

``emit`` records every emitted ``BusinessEvent`` to the trail: this module maps an event onto row
columns (:func:`event_columns`) and persists it via the
:class:`~apps.shared.events.repository.EventRepository` — on the request's own unit of work
(:func:`persist_fact`), so the fact commits iff the action commits (atomic). Only the fallback path
(no ambient session: auth signals, seeders) stays best-effort on a detached admin session.

Reading the trail back for a surface is a separate concern: the humanized activity feed and the
contribution calendar live in :mod:`apps.shared.events.timeline` (pure presentation).
"""

import asyncio
from dataclasses import fields, is_dataclass
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from apps.shared.events.repository import EventRepository
from apps.shared.events.types import BusinessEvent
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


async def insert_business_event(
    *,
    session: AsyncSession | None = None,
    kind: str,
    level: str,
    icon: str | None = None,
    user_id: str | None,
    ip: str | None,
    org_id: str | None,
    entity_id: str | None = None,
    request_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """Write one business-events row.

    With ``session`` (a request's unit of work), the row rides that transaction — it commits iff the
    action commits, and a failure propagates (atomic). Without one, a **best-effort** admin write on
    a fresh session that swallows failures (auth signals, seeders, non-request contexts)."""

    async def write(s: AsyncSession) -> None:
        """Persist the row on ``s`` with the actor handle denormalized; the caller commits."""
        repo = EventRepository(s)
        stored = dict(payload) if payload else {}
        handle = await repo.actor_handle(user_id)
        if handle:
            stored["actor"] = handle  # denormalized 'who' — RLS hides co-members' profiles
        await repo.save(
            kind=kind,
            level=level,
            icon=icon,
            user_id=user_id,
            ip=ip,
            org_id=org_id,
            entity_id=entity_id,
            request_id=request_id,
            payload=stored or None,
        )

    if session is not None:
        await write(session)
        return
    try:
        async with admin_session_factory()() as own:
            await write(own)
            await own.commit()
    except Exception:
        log.warning("business_event.write_failed", kind=kind, user_id=user_id)


# Field-name substrings that must never reach the persisted payload verbatim (e.g.
# ``UserCreated.access_token``). Matched case-insensitively against each field's name.
_REDACT_SUBSTRINGS = ("token", "password", "secret")


def _loggable_payload(event: BusinessEvent) -> dict[str, Any]:
    """The event's instance fields as a plain dict, with secret-named fields redacted — one place
    decides what of an event is safe to serialize into the trail's ``payload``."""
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if any(s in f.name.lower() for s in _REDACT_SUBSTRINGS):
            payload[f.name] = "***" if value is not None else None
        else:
            payload[f.name] = value
    return payload


def event_columns(event: BusinessEvent) -> dict[str, Any]:
    """Map a ``BusinessEvent`` onto the ``business_events`` row fields — scoping lifted to their own
    columns, the rest to ``payload``, ``ip``/``request_id`` read from the request contextvars."""
    ctx = get_contextvars()
    payload = _loggable_payload(event)
    payload.pop("actor_id", None)
    payload.pop("org_id", None)
    payload.pop("entity_id", None)  # promoted to its own column, like actor_id/org_id
    return dict(
        kind=event.kind,
        level=event.level,
        icon=event.icon,
        user_id=event.actor_id,
        ip=ctx.get("ip"),
        org_id=event.org_id,
        entity_id=event.entity_id,
        request_id=ctx.get("request_id"),
        payload=payload or None,
    )


async def persist_fact(event: BusinessEvent, session: AsyncSession | None) -> None:
    """``emit``'s persist path.

    With an ambient request session, the fact is written on it — atomic with the action (commits
    iff the mutation commits). With none (auth signals, non-request contexts) there is no
    transaction to join, so it is a best-effort detached write off the critical path — never
    blocking or failing the caller."""
    columns = event_columns(event)
    if session is not None:
        await insert_business_event(session=session, **columns)
    else:
        asyncio.create_task(insert_business_event(**columns))
