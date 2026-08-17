"""The event bus — the one registration + emit surface every app uses.

Four methods, nothing else:

- ``declare(*event_types)`` — record, at mount, that this app's facts are live. ``emit`` refuses an
  undeclared event, so a disabled app cannot emit.
- ``emit(event, session)`` — **persist the fact** to the ``business_events`` journal on the session
  the caller names (atomic with the action). That is *all* it does: no handler runs here. The
  :mod:`apps.shared.events.listener` reads the persisted journal after commit and runs the
  reactions, so a producer never waits on, or fails from, a consumer.
- ``on(event_type, handler)`` — register a **durable, exactly-once** consumer, run by the listener
  off the journal (one queued task per consumer, retried then parked). Handler signature is
  ``(session, event)``.
- ``spread(event_type, handler)`` — register a **run-everywhere** handler (config reload), replayed
  by the listener **per instance** off the journal.

The three registration methods write into an :class:`~apps.shared.events.wiring.EventWiring` —
*who emits what, and who reacts* — and ``emit`` reads its ownership gate. It is the process's
:data:`~apps.shared.events.wiring.wiring` unless a test hands over its own, and the bus is that
wiring's writer, not its owner: the listener and the console import it directly.
What events *exist* is not here at all — a class registers itself in
:data:`~apps.shared.events.catalog.catalog` at import, with no mount involved.

Runtime publishers import the process-wide :data:`events` singleton directly; mount wires handlers
onto ``host.events`` — the same ``events`` in production (``host = Host(events=events)``) — so
registration and emit share one wiring.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.repository import EventRepository
from apps.shared.events.types import BusinessEvent
from apps.shared.events.wiring import EventWiring
from apps.shared.events.wiring import wiring as process_wiring
from apps.shared.queue import register_task_handler

E = TypeVar("E", bound=BusinessEvent)

# Durable consumer signature: the reconstructed, typed event on the worker's session.
AsyncEventHandler = Callable[[AsyncSession, Any], Awaitable[None]]


def _delivery_context(payload: dict[str, Any]) -> dict[str, str]:
    """The correlation keys to bind on a reaction's log context, read off the task payload — the
    originating ``request_id`` and the fact's own ``event_id`` (its causation). Only present keys
    are bound: a fact emitted outside a request (an auth signal, a background job) has no
    ``request_id``, and binding a ``None`` would only add a null column to every reaction's logs."""
    return {
        key: str(payload[key]) for key in ("request_id", "event_id") if payload.get(key) is not None
    }


class EventBus:
    """Registration + emit. What a mount wires goes into an
    :class:`~apps.shared.events.wiring.EventWiring` — the process's by default, which its readers
    import for themselves; reactions run in the listener off the persisted journal, never here."""

    def __init__(self, wiring: EventWiring | None = None) -> None:
        # The bus *writes* the wiring, it does not own it: the listener and the console read the
        # same one by importing it, rather than reaching through an emitter to find who reacts.
        # A test that wants its own subscriptions passes a fresh `EventWiring()`.
        self._wiring = wiring if wiring is not None else process_wiring

    def declare(self, *event_types: type[BusinessEvent]) -> None:
        """Record, at mount, the events this app emits — each names its own owner (``app_name``),
        so declaring says *these facts are live in this process*, nothing more. :meth:`emit` then
        refuses any undeclared event (a disabled app never declares, so its facts can't be
        emitted)."""
        self._wiring.declare(*event_types)

    async def emit(self, event: BusinessEvent, session: AsyncSession) -> None:
        """Persist the fact on ``session`` — and only that. Refuses an undeclared event (a fact must
        be owned). Reactions run in the listener off the persisted journal after commit, so ``emit``
        never runs a handler, waits on one, or fails from one.

        The session is required, with no default and no ambient lookup: durability is stated at the
        call site rather than inherited from a dependency chosen three layers up the route, and the
        type checker enumerates those call sites."""
        self._require_declared(event)
        await EventRepository(session).record(event)

    def _require_declared(self, event: BusinessEvent) -> None:
        """The ownership gate: an emitted fact is always some app's."""
        if not self._wiring.is_declared(type(event)):
            raise ValueError(
                f"{type(event).__name__} ({event.kind!r}) is emitted but declared by no app"
            )

    def on(
        self,
        event_type: type[BusinessEvent],
        handler: AsyncEventHandler,
        *,
        name: str,
        app: str,
        as_actor: bool = False,
        idempotent: bool = True,
    ) -> None:
        """Register a durable, exactly-once consumer of ``event_type`` (and its subclasses), run by
        the listener off the journal after commit (one queued task per consumer, retry/park).
        ``name`` disambiguates consumers of the same event; ``app`` is the listening app (console's
        reaction graph); ``as_actor`` runs under the actor's RLS claims (else admin); ``idempotent``
        guards re-delivery via the ``consumed`` ledger."""
        topic = self._wiring.add_consumer(event_type, name, as_actor=as_actor, app=app)
        register_task_handler(
            topic, self._make_wrapper(event_type, handler, topic, idempotent=idempotent)
        )

    def spread(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        """Register a run-everywhere handler — for config propagation (a settings reload). The
        listener runs it **per instance** off the journal (no claim, no dispatch mark), so every
        process applies the change. Handlers must be idempotent (re-delivery is harmless).

        ``event_type`` is a ``BusinessEvent``, and cannot be anything else: the listener finds these
        facts by scanning the journal for their ``kind``, so a type that has none would register a
        handler nothing could ever call."""
        self._wiring.add_spread_handler(event_type, handler)

    @staticmethod
    def _make_wrapper(
        event_type: type[BusinessEvent],
        handler: AsyncEventHandler,
        topic: str,
        *,
        idempotent: bool,
    ) -> Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]:
        """Adapt a typed durable handler to the queue's ``(session, payload)`` task contract, with
        the idempotency guard folded in — one place bridges the durable queue to ``bus.on``."""

        async def wrapper(session: AsyncSession, payload: dict[str, Any]) -> None:
            if idempotent and await EventRepository(session).already_consumed(
                topic, payload["event_id"]
            ):
                return  # a re-delivery — the ledger entry (from the first run) makes this a no-op
            # Correlate the reaction's logs with the fact that triggered it: request_id is the
            # originating stimulus (so a reaction joins the emitting request's timeline), event_id
            # the immediate cause. The reaction runs off the journal, minutes-to-days after the
            # request, on a background task with no request context of its own — so bind them here.
            with structlog.contextvars.bound_contextvars(**_delivery_context(payload)):
                await handler(session, event_type.from_payload(payload))

        return wrapper


# Process-wide singleton, writing the process-wide wiring. Runtime code emits on this directly; the
# production Host is built with ``events=events`` so its mount-time ``.on(...)`` registrations and
# the singleton's ``emit`` share one wiring.
events = EventBus()
