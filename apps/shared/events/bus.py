"""The event bus — the one registration + emit surface every app uses.

Three methods, nothing else:

- ``emit(event, session)`` — **persist the fact** to the ``business_events`` trail on the caller's
  transaction (atomic with the action). That is *all* it does: no handler runs here. The
  :mod:`apps.shared.events.listener` reads the persisted log after commit and runs the reactions, so
  a producer never waits on, or fails from, a consumer.
- ``on(event_type, handler)`` — register a **durable, exactly-once** consumer, run by the listener
  off the trail (one task-queue row per consumer, retried then parked). Handler signature is
  ``(session, event)``.
- ``spread(event_type, handler)`` — register a **run-everywhere** handler (config reload), replayed
  by the listener **per instance** off the trail.

Runtime publishers import the process-wide :data:`events` singleton directly. Mount wires handlers
onto ``host.events`` — the same ``events`` in production (``host = Host(events=events)``) — so
registration and emit share one registry.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.repository import EventRepository
from apps.shared.events.store import persist_fact
from apps.shared.events.types import BusinessEvent, reconstruct
from apps.shared.persistence.uow import current_session
from apps.shared.queue import register_task_handler

E = TypeVar("E")

# Durable consumer signature: the reconstructed, typed event on the worker's session.
AsyncEventHandler = Callable[[AsyncSession, Any], Awaitable[None]]


@dataclass(frozen=True)
class _Sub:
    """A durable consumer of an event type, keyed by its queue ``topic``."""

    topic: str
    as_actor: bool


class EventBus:
    """Registration + emit. Reactions run in the listener, off the persisted trail — never here."""

    def __init__(self) -> None:
        # Two in-process registries the listener reads to deliver off the trail: ``spread`` handlers
        # (replayed per instance) and ``on`` durable consumers (fanned to one task-queue row each).
        # ``emit`` itself just persists the fact.
        self._spread_subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)
        self._async_subs: dict[type, list[_Sub]] = {}

    async def emit(self, event: BusinessEvent, session: AsyncSession | None = None) -> None:
        """Persist the fact — and only that.

        Recorded to the ``business_events`` trail on ``session`` (or the ambient request unit of
        work), atomic with the action, so the fact commits iff the mutation commits. Every reaction
        (``on`` consumers, ``spread`` handlers) runs in the listener off the persisted log after
        commit — so ``emit`` never runs a handler, waits on one, or fails from one.
        """
        await persist_fact(event, session or current_session())

    def on(
        self,
        event_type: type[BusinessEvent],
        handler: AsyncEventHandler,
        *,
        name: str,
        as_actor: bool = False,
        idempotent: bool = True,
    ) -> None:
        """Register a durable, exactly-once consumer of ``event_type`` (and its subclasses).

        Run by the :mod:`apps.shared.events.listener` off the trail **after commit**, never in
        :meth:`emit`: one task-queue row per consumer, with retry/park. ``name`` disambiguates this
        consumer among the event's consumers (topic ``evt:<kind>:<name>``, unique per event type).
        ``as_actor`` runs the handler under the event actor's RLS claims (else on the admin
        session); ``idempotent`` guards re-delivery via the ``consumed`` ledger.
        """
        topic = f"evt:{event_type.kind}:{name}"
        subs = self._async_subs.setdefault(event_type, [])
        if any(s.topic == topic for s in subs):
            raise ValueError(f"duplicate consumer {name!r} for {event_type.__name__}")
        subs.append(_Sub(topic=topic, as_actor=as_actor))
        register_task_handler(topic, self._make_wrapper(event_type, handler, topic, idempotent))

    def subscribers_for(self, event_type: type) -> list[_Sub]:
        """All durable subscribers keyed on the event's MRO — a base-type subscription catches
        subclasses, mirroring :meth:`emit`'s dispatch. Read by the listener to fan a fact out."""
        collected: list[_Sub] = []
        for klass in event_type.__mro__:
            collected.extend(self._async_subs.get(klass, ()))
        return collected

    @staticmethod
    def _make_wrapper(
        event_type: type[BusinessEvent], handler: AsyncEventHandler, topic: str, idempotent: bool
    ) -> Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]:
        """Adapt a typed durable handler to the queue's ``(session, payload)`` task contract, with
        the idempotency guard folded in — one place bridges the durable queue to ``bus.on``."""

        async def wrapper(session: AsyncSession, payload: dict[str, Any]) -> None:
            if idempotent and await EventRepository(session).already_consumed(
                topic, payload["event_id"]
            ):
                return  # a re-delivery — the ledger row (from the first run) makes this a no-op
            await handler(session, reconstruct(event_type, payload))

        return wrapper

    def spread(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        """Register a handler that must run on **every** process when the event is emitted.

        The "run everywhere" mode — for config propagation (a settings reload). Registration only:
        the :mod:`apps.shared.events.listener` reads the persisted fact off the trail and runs these
        handlers **per instance** (no claim, no dispatch mark), so every process applies the change.
        Handlers are idempotent (a reload is a plain assignment), so re-delivery is harmless.
        """
        self._spread_subs[event_type].append(handler)

    def _handlers_for(
        self,
        event: BusinessEvent,
        subs: dict[type, list[Callable[[Any], Awaitable[object]]]],
        seen: set[int],
    ) -> Iterator[Callable[[Any], Awaitable[object]]]:
        """Handlers subscribed to the event's runtime type or any base, most-specific first, each
        once. Read by the listener to dispatch ``spread`` handlers off a persisted fact."""
        for klass in type(event).__mro__:
            for handler in subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    yield handler


# Process-wide singleton. Runtime code emits on this directly; the production Host
# is built with ``events=events`` so its mount-time ``.on(...)`` registrations land here too.
events = EventBus()
