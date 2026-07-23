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

The bus holds no collected state of its own: what events exist and who listens to them live in the
:class:`~apps.shared.events.registry.EventRegistry` (injectable, default the process singleton).
Runtime publishers import the process-wide :data:`events` singleton directly; mount wires handlers
onto ``host.events`` — the same ``events`` in production (``host = Host(events=events)``) — so
registration and emit share one registry.
"""

from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.repository import EventRepository
from apps.shared.events.store import persist_fact
from apps.shared.events.types import BusinessEvent, reconstruct
from apps.shared.persistence.uow import current_session
from apps.shared.queue import register_task_handler

E = TypeVar("E")

# Durable consumer signature: the reconstructed, typed event on the worker's session.
AsyncEventHandler = Callable[[AsyncSession, Any], Awaitable[None]]


class EventBus:
    """Registration + emit. The collected knowledge (catalog, subscriptions) lives in the
    :class:`~apps.shared.events.registry.EventRegistry`; reactions run in the listener off the
    persisted trail — never here."""

    def __init__(self, registry: EventRegistry) -> None:
        # The bus always rides an explicit registry: production shares the singleton (see below);
        # a test injects a fresh one to isolate its subscriptions (the catalog stays shared — event
        # classes register once at import).
        self.registry = registry

    def declare(self, app: str, *event_types: type[BusinessEvent]) -> None:
        """Declare, at mount, the events ``app`` emits — recording their owner in the registry.

        The event's kind prefix must be ``app`` (``todo.*`` → ``todo``), so an app cannot claim
        another's events. :meth:`emit` then refuses any event no app declared, catching a typo or a
        forgotten declaration at the emit site rather than silently writing an unowned fact.
        """
        self.registry.declare(app, *event_types)

    async def emit(self, event: BusinessEvent, session: AsyncSession | None = None) -> None:
        """Persist the fact — and only that.

        Refuses an event no app declared (:meth:`declare`) — an emitted fact must be owned.
        Otherwise recorded to the ``business_events`` trail on ``session`` (or the ambient request
        unit of work), atomic with the action, so the fact commits iff the mutation commits. Every
        reaction (``on`` consumers, ``spread`` handlers) runs in the listener off the persisted log
        after commit — so ``emit`` never runs a handler, waits on one, or fails from one.
        """
        if not self.registry.is_declared(type(event)):
            raise ValueError(
                f"{type(event).__name__} ({event.kind!r}) is emitted but declared by no app"
            )
        await persist_fact(event, session or current_session())

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
        """Register a durable, exactly-once consumer of ``event_type`` (and its subclasses).

        Run by the :mod:`apps.shared.events.listener` off the trail **after commit**, never in
        :meth:`emit`: one task-queue row per consumer, with retry/park. ``name`` disambiguates this
        consumer among the event's consumers (topic ``evt:<kind>:<name>``, unique per event type);
        ``app`` is the listening app (for the console's event → reaction graph). ``as_actor`` runs
        the handler under the event actor's RLS claims (else on the admin session); ``idempotent``
        guards re-delivery via the ``consumed`` ledger.
        """
        topic = self.registry.add_async(event_type, name, as_actor=as_actor, app=app)
        register_task_handler(topic, self._make_wrapper(event_type, handler, topic, idempotent))

    def spread(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        """Register a handler that must run on **every** process when the event is emitted.

        The "run everywhere" mode — for config propagation (a settings reload). Registration only:
        the :mod:`apps.shared.events.listener` reads the persisted fact off the trail and runs these
        handlers **per instance** (no claim, no dispatch mark), so every process applies the change.
        Handlers are idempotent (a reload is a plain assignment), so re-delivery is harmless.
        """
        self.registry.add_spread(event_type, handler)

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


# Process-wide singleton, on the process-wide registry. Runtime code emits on this directly; the
# production Host is built with ``events=events`` so its mount-time ``.on(...)`` registrations and
# the singleton's ``emit`` share one registry.
events = EventBus(registry)
