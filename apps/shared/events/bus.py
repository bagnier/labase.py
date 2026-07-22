"""Type-keyed event bus — synchronous, in-process pub/sub, plus the persist step for facts.

``emit(event)`` is push/command: it first persists a ``BusinessEvent`` to the trail (atomic with
the action), then runs every sync ``on`` handler, propagating the first exception so the caller can
compensate.

Durable **async** consumers are *not* run here: a ``BusinessEvent`` persisted by ``emit`` is read
back from the log by the :mod:`apps.shared.events.tailer`, which fans it out to
:func:`~apps.shared.events.outbox.on_async` subscribers after commit — so the producer never
waits on, or fails from, a consumer. The *pull* half of collaboration (``collect`` a query's
contributions) lives in :mod:`apps.shared.contribs` — a provider registry, not events.

Runtime publishers import the process-wide :data:`events` singleton directly — a focused
collaborator, not the whole :class:`~apps.shared.host.Host`. Mount wires handlers onto
``host.events``, which *is* this same ``events`` in production (``host = Host(events=events)``),
so registration and dispatch share one registry.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Iterator
from typing import Any, TypeVar

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.store import persist_fact
from apps.shared.events.types import BusinessEvent
from apps.shared.persistence.uow import current_session

log = structlog.get_logger("labase.shared.bus")

E = TypeVar("E")

# The single Postgres channel every "run everywhere" (``spread``) event broadcasts on. A process's
# SpreadListener LISTENs here and, woken, re-reads fresh state and applies its ``spread`` handlers.
SPREAD_CHANNEL = "spread"


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)
        self._spread_subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        self._subs[event_type].append(handler)

    def spread(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        """Register a handler that must run on **every** process when the event is emitted.

        This is the "run everywhere" mode — for config propagation (a settings reload), *not* a
        persisted business fact: ``spread`` events are never written to the trail. Delivery is a
        NOTIFY broadcast: ``emit`` only fires the signal, and each process's SpreadListener re-reads
        fresh state and runs these handlers via :meth:`deliver_spread`. The emitter is just another
        listener — it applies via its own LISTEN, once, so there is no PID or self-dedup to track.
        """
        self._spread_subs[event_type].append(handler)

    def _handlers_for(
        self,
        event: object,
        subs: dict[type, list[Callable[[Any], Awaitable[object]]]],
        seen: set[int],
    ) -> Iterator[Callable[[Any], Awaitable[object]]]:
        """Handlers subscribed to the event's runtime type or any base, most-specific first, each
        once. ``seen`` is threaded across calls so a handler registered on several MRO classes — or
        on both ``_subs`` and ``_spread_subs`` — runs a single time per dispatch."""
        for klass in type(event).__mro__:
            for handler in subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    yield handler

    async def emit(self, event: object, session: AsyncSession | None = None) -> None:
        """Persist the fact, run every sync ``on`` handler, and broadcast to ``spread`` listeners.

        A ``BusinessEvent`` is first recorded to the ``business_events`` trail on ``session`` (or
        the ambient request unit of work) — atomic with the action, so the fact commits iff the
        mutation commits. Non-``BusinessEvent`` signals are not persisted. Async consumers are not
        run here: the :mod:`apps.shared.events.tailer` reads the persisted log and fans each fact
        out to its :func:`~apps.shared.events.outbox.on_async` subscribers after commit, so the
        producer never waits on — or fails from — a consumer.

        ``on`` dispatch walks the event's MRO — handlers on the concrete type fire first (most
        specific), then any base class; a handler on several MRO classes runs once. ``spread``
        handlers are **not** run here: if the event has any, ``emit`` fires a NOTIFY so every
        process's SpreadListener re-reads fresh state and applies them (see :meth:`spread`).

        ``emit`` returns nothing — it is fire-and-forget. Handler return values were never consumed
        (and once ``on`` is fully durable/async, ``emit`` runs no handlers to return anything from).
        """
        # The fact first: a BusinessEvent is persisted on the request's own transaction (atomic
        # with the action; a best-effort admin write when no ambient session is in scope).
        if isinstance(event, BusinessEvent):
            await persist_fact(event, session or current_session())
        seen: set[int] = set()
        for handler in self._handlers_for(event, self._subs, seen):
            await handler(event)
        # "Run everywhere" events are delivered by NOTIFY broadcast, never in-process: fire the
        # signal so every instance (the emitter included, via its own LISTEN) re-reads and applies.
        if any(klass in self._spread_subs for klass in type(event).__mro__):
            await self._broadcast_spread(event, session)

    async def _broadcast_spread(self, event: object, session: AsyncSession | None) -> None:
        """Fire the spread NOTIFY on the caller's transaction (delivered on commit, so listeners see
        the committed change). Best-effort: with no session in scope, log and skip — the poll net in
        each SpreadListener still converges."""
        conn = session or current_session()
        if conn is None:
            log.warning("event.spread_no_session", event_type=type(event).__name__)
            return
        await conn.execute(text(f"NOTIFY {SPREAD_CHANNEL}"))

    async def deliver_spread(self, event: object) -> None:
        """Run this process's ``spread`` handlers for ``event`` — called by the SpreadListener on a
        NOTIFY (or its poll net) with freshly-read state, never by :meth:`emit`. Handlers are
        idempotent (a settings reload is a plain assignment), so re-delivery is harmless."""
        seen: set[int] = set()
        for handler in self._handlers_for(event, self._spread_subs, seen):
            await handler(event)


# Process-wide singleton. Runtime code emits on this directly; the production Host
# is built with ``events=events`` so its mount-time ``.on(...)`` registrations land here too.
events = EventBus()
