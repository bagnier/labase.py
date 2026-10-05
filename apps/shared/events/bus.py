"""The event bus: an app declares the facts it owns, emits them, and subscribes reactions
(AGENTS: `emit` records a fact and does only that).

Registrations land in an :class:`~apps.shared.events.wiring.EventWiring`, which the listener and the
console read directly; the bus writes it, it does not own it.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.repository import EventRepository
from apps.shared.events.types import BusinessEvent
from apps.shared.events.wiring import EventWiring
from apps.shared.events.wiring import wiring as process_wiring
from apps.shared.queue import delivery_context, register_task_handler

# Generic over the event so that a handler written for another fact fails the type check at mount,
# not with an ``AttributeError`` when the listener runs it.
type AsyncEventHandler[E: BusinessEvent] = Callable[[AsyncSession, E], Awaitable[None]]


class EventBus:
    """Registration + emit; reactions run in the listener, never here."""

    def __init__(self, wiring: EventWiring | None = None) -> None:
        self._wiring = wiring if wiring is not None else process_wiring

    def declare(self, *event_types: type[BusinessEvent]) -> None:
        """Mark the app's events as live; :meth:`emit` refuses the others, so a disabled app emits
        nothing."""
        self._wiring.declare(*event_types)

    async def emit(self, event: BusinessEvent, session: AsyncSession) -> None:
        """Persist the fact on ``session``, atomic with the caller's mutation.

        ``session`` has no default: durability is chosen at the call site, not inherited from the
        route's dependencies. Raises ``ValueError`` on an undeclared event."""
        self._require_declared(event)
        await EventRepository(session).record(event)

    def _require_declared(self, event: BusinessEvent) -> None:
        if not self._wiring.is_declared(type(event)):
            raise ValueError(
                f"{type(event).__name__} ({event.kind!r}) is emitted but declared by no app"
            )

    def on[E: BusinessEvent](
        self,
        event_type: type[E],
        handler: AsyncEventHandler[E],
        *,
        name: str,
        app: str,
        as_actor: bool = False,
        idempotent: bool = True,
    ) -> None:
        """Register a durable consumer of ``event_type`` and its subclasses: one queued task per
        fact, retried then parked.

        ``name`` tells apart consumers of one event; ``app`` is the listening app (console's
        reaction graph); ``as_actor`` runs under the actor's RLS claims instead of admin;
        ``idempotent`` skips a re-delivery already in the ``consumed_events`` ledger."""
        topic = self._wiring.add_consumer(event_type, name, as_actor=as_actor, app=app)
        register_task_handler(
            topic, self._make_wrapper(event_type, handler, topic, idempotent=idempotent)
        )

    def spread[E: BusinessEvent](
        self, event_type: type[E], handler: Callable[[E], Awaitable[object]]
    ) -> None:
        """Register a handler every instance runs, e.g. a settings reload. No claim: it must be
        idempotent."""
        self._wiring.add_spread_handler(event_type, handler)

    @staticmethod
    def _make_wrapper[E: BusinessEvent](
        event_type: type[E],
        handler: AsyncEventHandler[E],
        topic: str,
        *,
        idempotent: bool,
    ) -> Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]:
        """Adapt a typed handler to the queue's ``(session, payload)`` task contract."""

        async def wrapper(session: AsyncSession, payload: dict[str, Any]) -> None:
            if idempotent and await EventRepository(session).already_consumed(
                topic, payload["event_id"]
            ):
                return
            # Joins the reaction's logs to the emitting request's timeline. ``TaskWorker._process``
            # binds the same around the whole task; this one covers a direct call.
            with structlog.contextvars.bound_contextvars(**delivery_context(payload)):
                await handler(session, event_type.from_payload(payload))

        return wrapper


# The production Host is built with ``events=events``: mount registrations and runtime emits share
# one wiring.
events = EventBus()
