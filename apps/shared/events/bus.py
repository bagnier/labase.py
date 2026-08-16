"""The event bus — the one registration + emit surface every app uses.

Four methods, nothing else:

- ``declare(*event_types)`` — record, at mount, that this app's facts are live. ``emit`` refuses an
  undeclared event, so a disabled app cannot emit.
- ``emit(event, session)`` — **persist the fact** to the ``business_events`` trail on the session
  the caller names (atomic with the action). That is *all* it does: no handler runs here. The
  :mod:`apps.shared.events.listener` reads the persisted trail after commit and runs the
  reactions, so a producer never waits on, or fails from, a consumer.
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

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.registry import EventRegistry, registry
from apps.shared.events.repository import EventRepository
from apps.shared.events.types import BusinessEvent
from apps.shared.queue import register_task_handler

E = TypeVar("E")

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
    """Registration + emit. The collected knowledge (catalog, subscriptions) lives in the
    :class:`~apps.shared.events.registry.EventRegistry`; reactions run in the listener off the
    persisted trail — never here."""

    def __init__(self, registry: EventRegistry) -> None:
        # The bus always rides an explicit registry: production shares the singleton (see below);
        # a test injects a fresh one to isolate its subscriptions (the catalog stays shared — event
        # classes register once at import).
        self.registry = registry

    def declare(self, *event_types: type[BusinessEvent]) -> None:
        """Record, at mount, the events this app emits — each names its own owner (``app_name``),
        so declaring says *these facts are live in this process*, nothing more. :meth:`emit` then
        refuses any undeclared event (a disabled app never declares, so its facts can't be
        emitted)."""
        self.registry.declare_events(*event_types)

    async def emit(self, event: BusinessEvent, session: AsyncSession) -> None:
        """Persist the fact on ``session`` — and only that. Refuses an undeclared event (a fact must
        be owned). Reactions run in the listener off the persisted trail after commit, so ``emit``
        never runs a handler, waits on one, or fails from one.

        The session is required, with no default and no ambient lookup. It used to fall back to the
        request's bound session, which made a fact's durability depend on a dependency chosen three
        layers up the route — two facts in one handler could carry different guarantees with nothing
        saying so. Now the call site states it, and the type checker enumerates the call sites."""
        self._require_declared(event)
        await EventRepository(session).record(event)

    def _require_declared(self, event: BusinessEvent) -> None:
        """The ownership gate: an emitted fact is always some app's."""
        if not self.registry.is_declared(type(event)):
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
        the listener off the trail after commit (one task-queue row per consumer, retry/park).
        ``name`` disambiguates consumers of the same event; ``app`` is the listening app (console's
        reaction graph); ``as_actor`` runs under the actor's RLS claims (else admin); ``idempotent``
        guards re-delivery via the ``consumed`` ledger."""
        topic = self.registry.register_single_action(event_type, name, as_actor=as_actor, app=app)
        register_task_handler(
            topic, self._make_wrapper(event_type, handler, topic, idempotent=idempotent)
        )

    def spread(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        """Register a run-everywhere handler — for config propagation (a settings reload). The
        listener runs it **per instance** off the trail (no claim, no dispatch mark), so every
        process applies the change. Handlers must be idempotent (re-delivery is harmless)."""
        self.registry.register_spread_action(event_type, handler)

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
                return  # a re-delivery — the ledger row (from the first run) makes this a no-op
            # Correlate the reaction's logs with the fact that triggered it: request_id is the
            # originating stimulus (so a reaction joins the emitting request's timeline), event_id
            # the immediate cause. The reaction runs off the trail, minutes-to-days after the
            # request, on a background task with no request context of its own — so bind them here.
            with structlog.contextvars.bound_contextvars(**_delivery_context(payload)):
                await handler(session, event_type.from_payload(payload))

        return wrapper


# Process-wide singleton, on the process-wide registry. Runtime code emits on this directly; the
# production Host is built with ``events=events`` so its mount-time ``.on(...)`` registrations and
# the singleton's ``emit`` share one registry.
events = EventBus(registry)
