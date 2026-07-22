"""Type-keyed event bus — synchronous, in-process pub/sub, plus the persist step for facts.

``emit(event)`` is push/command: it first persists a ``BusinessEvent`` to the trail (atomic with
the action), then runs every sync ``on`` handler, propagating the first exception so the caller can
compensate.

Durable **async** consumers are *not* run here: a ``BusinessEvent`` persisted by ``emit`` is read
back from the log by the :mod:`apps.shared.events.listener`, which fans it out to
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

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events.store import persist_fact
from apps.shared.events.types import BusinessEvent
from apps.shared.persistence.uow import current_session

E = TypeVar("E")


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)
        self._spread_subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        self._subs[event_type].append(handler)

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

    async def emit(self, event: BusinessEvent, session: AsyncSession | None = None) -> None:
        """Persist the fact, then run every sync ``on`` handler.

        The event — always a ``BusinessEvent`` — is first recorded to the ``business_events`` trail
        on ``session`` (or the ambient request unit of work), atomic with the action, so the fact
        commits iff the mutation commits. Two deliveries then ride the persisted log, off this call:
        the :mod:`apps.shared.events.listener` fans each fact out to its
        :func:`~apps.shared.events.outbox.on_async` consumers (durable, exactly-once) and runs any
        ``spread`` handlers per instance — so the producer never waits on, or fails from, a
        consumer.

        ``on`` dispatch walks the event's MRO — handlers on the concrete type fire first (most
        specific), then any base class; a handler on several MRO classes runs once.
        """
        # The fact first: persisted on the request's own transaction (atomic with the action; a
        # best-effort admin write when no ambient session is in scope).
        await persist_fact(event, session or current_session())
        seen: set[int] = set()
        for handler in self._handlers_for(event, self._subs, seen):
            await handler(event)


# Process-wide singleton. Runtime code emits on this directly; the production Host
# is built with ``events=events`` so its mount-time ``.on(...)`` registrations land here too.
events = EventBus()
