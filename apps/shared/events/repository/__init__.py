"""The business-events repository — the one owner of ``business_events``.

:class:`EventRepository` is :class:`~apps.shared.persistence.repository.BaseRepository` over
:class:`BusinessEventLog`, composed from three concern modules: ``_write`` (append a fact + the
``event → row`` mapping), ``_delivery`` (the listener's claim/mark/scan + consumed ledger), and
``_read`` (``search``/``daily_counts``). Humanizing rows is elsewhere (``timeline``); so is emit's
session policy (the bus's ``_persist_fact``).

This composition root wires the mixins together and re-exports the public surface, so callers keep
``from apps.shared.events.repository import EventRepository``.
"""

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository._delivery import _DispatchesEvents
from apps.shared.events.repository._read import _ReadsEvents
from apps.shared.events.repository._write import _WritesEvents, event_to_log
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


class EventRepository(_WritesEvents, _DispatchesEvents, _ReadsEvents):
    """All ``business_events`` SQL, bound to one session — the three concern mixins composed."""


async def insert_business_event(
    *,
    session: AsyncSession | None = None,
    kind: str,
    level: str,
    icon: str | None = None,
    user_id: uuid.UUID | None,
    ip: str | None,
    org_id: uuid.UUID | None,
    entity_id: uuid.UUID | None = None,
    request_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """Write a row from explicit columns — the seeding / non-event writer. With a ``session`` the
    row rides that transaction (atomic); without one, a best-effort admin write that swallows
    failures (seeders, tests)."""

    async def write(s: AsyncSession) -> None:
        repo = EventRepository(s)
        stored = dict(payload) if payload else {}
        handle = await repo.user_handle(user_id)
        if handle:
            stored["actor_name"] = handle  # denormalized 'who' — RLS hides co-members' profiles
        await repo.save(
            BusinessEventLog(
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


__all__ = ["EventRepository", "event_to_log", "insert_business_event"]
