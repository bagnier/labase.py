"""Type-keyed async event bus — the generic pub/sub mechanism every context wires into.

Two primitives:

- ``emit(event)`` — push/command: run all handlers, propagate the first exception (caller
  can compensate), return their results.
- ``collect(query)`` — pull/query: run all handlers, isolate failures (log + skip), return
  successful results.

Runtime publishers/collectors import the process-wide :data:`bus` singleton directly — a
focused collaborator, not the whole :class:`~apps.shared.host.Host`. Mount wires handlers
onto ``host.events``, which *is* this same ``bus`` in production (``host = Host(events=bus)``),
so registration and dispatch share one registry.
"""

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.outbox import fan_out_durable

log = structlog.get_logger("labase.shared.bus")

E = TypeVar("E")


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        self._subs[event_type].append(handler)

    async def emit(self, event: object, session: AsyncSession | None = None) -> list[object]:
        """Run every sync handler for this event, then durably fan out to its async subscribers.

        Dispatch walks the event's MRO — handlers registered on the concrete type fire first
        (most specific), then handlers registered on any base class. This lets a single
        subscriber on a base (e.g. the business-events persister on ``BusinessEvent``) catch
        every subclass, while exact-type subscribers keep working unchanged. A handler
        registered on several classes in the MRO runs once.

        After the sync handlers, :func:`~apps.shared.outbox.fan_out_durable` enqueues one durable
        task per :func:`~apps.shared.outbox.on_async` subscriber — on ``session`` or the ambient
        request unit of work — so any event can grow async behavior without its producer changing.
        The enqueue rides the same transaction: a sync-handler exception (propagated below) or a
        later rollback discards the outbox rows too. It is a zero-cost no-op when the event has no
        async subscribers, so audit-only signals pay nothing.

        The bus does *not* log the dispatch itself. Business events are recorded durably to the
        trail by the persister (with full user/org/entity/request scoping); the handful of
        non-business *signals* (``UserCreated``/``UserDeleted``/``SettingsChanged``) are internal
        plumbing whose meaningful outcome is already an audited business event — a generic
        ``event.emitted`` line for them would only be redundant noise in the logs viewer.
        """
        # Command semantics: results are typed `object`, not `Any` — callers fire and discard
        # them. (`collect` keeps `Any`: its callers consume heterogeneous typed aggregates.)
        results: list[object] = []
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    results.append(await handler(event))
        await fan_out_durable(event, session)
        return results

    async def collect(self, query: object) -> list[Any]:
        """Run every handler for this query type; log and skip failing handlers.

        A handler failure is a bug: ``log.exception`` feeds it to the error tracker through the
        capture processor (``event_type`` names the failing query so it survives into the issue
        context). The capture drain runs recording under a reentrancy guard, so a tracker
        handler that itself fails here cannot recurse.
        """
        results: list[Any] = []
        for handler in self._subs[type(query)]:
            try:
                results.append(await handler(query))
            except Exception:
                log.exception(
                    "query.handler_failed",
                    handler=repr(handler),
                    event_type=type(query).__name__,
                )
        return results


# Process-wide singleton. Runtime code emits/collects on this directly; the production Host
# is built with ``events=bus`` so its mount-time ``.on(...)`` registrations land here too.
bus = EventBus()
