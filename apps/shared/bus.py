"""Type-keyed async event bus — the generic pub/sub mechanism every context wires into.

Two ways to fan an event out to its handlers, differing only in failure policy:

- ``emit(event)`` — push/command: run all handlers, propagate the first exception (caller
  can compensate), return their results.
- ``notify(event)`` — push/signal: run all handlers, isolate failures (log + skip), return
  the successful results. For facts whose observers must never break the emitter (error
  capture fans out to trackers this way — a down tracker can't worsen what it tracks).

Both then durably fan out to the event's :func:`~apps.shared.outbox.on_async` subscribers.
The *pull* half of collaboration (``collect`` a query's contributions) lives in a separate
object, :mod:`apps.shared.contribs` — it is a provider registry, not events.

Runtime publishers import the process-wide :data:`events` singleton directly — a focused
collaborator, not the whole :class:`~apps.shared.host.Host`. Mount wires handlers onto
``host.events``, which *is* this same ``events`` in production (``host = Host(events=events)``),
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

    async def notify(self, event: object, session: AsyncSession | None = None) -> list[Any]:
        """Fan an event out to its handlers like :meth:`emit`, but isolate each failure.

        Same MRO dispatch and durable fan-out as ``emit``; the only difference is the failure
        policy — a handler that raises is logged and skipped instead of propagating. This is for
        facts whose observers must never break the emitter: error capture fans ``ExceptionCaptured``
        out this way so a failing tracker cannot worsen the error it tracks. The ``log.exception``
        feeds the failing handler to the tracker through the capture processor; the drain runs it
        under a reentrancy guard, so a tracker handler that itself fails here cannot recurse.
        """
        results: list[Any] = []
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    try:
                        results.append(await handler(event))
                    except Exception:
                        log.exception(
                            "event.notify_handler_failed",
                            handler=repr(handler),
                            event_type=type(event).__name__,
                        )
        await fan_out_durable(event, session)
        return results


# Process-wide singleton. Runtime code emits/notifies on this directly; the production Host
# is built with ``events=events`` so its mount-time ``.on(...)`` registrations land here too.
events = EventBus()
