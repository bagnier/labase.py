"""The durable async-consumer registry — how a business event grows at-least-once async behavior.

An :func:`on_async` subscriber registers a consumer for an event type (and a task handler for its
topic). The delivery itself is driven by the :mod:`apps.shared.tailer`: it reads the persisted
``business_events`` log and, per fact, enqueues one task-queue row per subscriber this module knows
(:func:`subscribers_for`). The per-process ``TaskWorker`` runs each row with its own
retry/backoff/park, and competing consumers across instances stay safe via ``SKIP LOCKED``.

Design notes:

- **One topic per subscriber** (``evt:<kind>:<name>``). The tailer fans a fact out to each, so every
  consumer keeps an independent task row — one poison message parks that consumer alone, not the
  whole event. The queue's one-handler-per-topic dispatch is unchanged.
- **Typed events, not dicts.** The subscriber receives the reconstructed event
  (``handler(session, event)``); the string topic is a transport detail.
- **At-least-once → idempotency.** ``idempotent=True`` guards a consumer with the ``consumed``
  ledger (:func:`already_consumed`, keyed on the business_events row id) in the handler's own
  transaction, so a re-delivery no-ops.
- **RLS.** ``as_actor=True`` (default) runs the handler under the event actor's claims (the queue
  convention); ``as_actor=False`` runs it on the admin session — for server-owned aggregation that
  no tenant should be able to write directly.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, fields
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent
from apps.shared.queue import register_task_handler

log = structlog.get_logger("labase.shared.outbox")

# Consumer signature: the reconstructed, typed event on the worker's session.
AsyncEventHandler = Callable[[AsyncSession, Any], Awaitable[None]]


@dataclass(frozen=True)
class _Sub:
    topic: str
    as_actor: bool


# Event type → its durable subscribers. Populated at mount by on_async, like bus.on for sync subs.
_async_subs: dict[type, list[_Sub]] = {}


def reset_async_subs() -> None:
    """Clear the durable-subscriber registry — for test isolation."""
    _async_subs.clear()


def on_async(
    event_type: type[BusinessEvent],
    name: str,
    handler: AsyncEventHandler,
    *,
    as_actor: bool = True,
    idempotent: bool = False,
) -> None:
    """Subscribe ``handler`` to durable, async deliveries of ``event_type`` (and its subclasses).

    ``name`` disambiguates this consumer among the event's subscribers (→ topic
    ``evt:<kind>:<name>``); it must be unique per event type. Registered at mount, exactly like a
    bus subscription plus a task handler — the producer's ``emit`` site never changes.
    """
    topic = f"evt:{event_type.kind}:{name}"
    subs = _async_subs.setdefault(event_type, [])
    if any(s.topic == topic for s in subs):
        raise ValueError(f"duplicate async subscriber {name!r} for {event_type.__name__}")
    subs.append(_Sub(topic=topic, as_actor=as_actor))
    register_task_handler(topic, _make_wrapper(event_type, handler, topic, idempotent))


def _make_wrapper(
    event_type: type[BusinessEvent], handler: AsyncEventHandler, topic: str, idempotent: bool
) -> Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]:
    """Adapt a typed async handler to the queue's ``(session, payload)`` task contract."""

    async def wrapper(session: AsyncSession, payload: dict[str, Any]) -> None:
        if idempotent and await already_consumed(session, topic, payload["event_id"]):
            return  # a re-delivery — the ledger row (from the first run) makes this a no-op
        await handler(session, _reconstruct(event_type, payload))

    return wrapper


def _reconstruct(event_type: type[BusinessEvent], payload: dict[str, Any]) -> BusinessEvent:
    """Rebuild the frozen event from its stored payload (dropping transport-only keys)."""
    names = {f.name for f in fields(event_type)}
    return event_type(**{k: v for k, v in payload.items() if k in names})


def subscribers_for(event_type: type) -> list[_Sub]:
    """All durable subscribers keyed on the event's MRO — a base-type subscription catches
    subclasses, mirroring ``EventBus.emit``'s dispatch. Read by the tailer to fan a fact out."""
    collected: list[_Sub] = []
    for klass in event_type.__mro__:
        collected.extend(_async_subs.get(klass, ()))
    return collected


async def already_consumed(session: AsyncSession, topic: str, event_id: int) -> bool:
    """Mark ``(topic, event_id)`` consumed; return whether it was **already** there.

    Insert-or-nothing against the ``consumed`` ledger: ``False`` the first time (freshly marked),
    ``True`` on a re-delivery. Runs on the handler's session, so it commits/rolls back atomically
    with the handler's own writes. ``event_id`` is the business_events row id."""
    result = await session.execute(
        text(
            "INSERT INTO consumed (topic, event_id) VALUES (:topic, CAST(:event_id AS bigint)) "
            "ON CONFLICT DO NOTHING RETURNING topic"
        ),
        {"topic": topic, "event_id": event_id},
    )
    return result.first() is None
