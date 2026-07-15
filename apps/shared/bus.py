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

import dataclasses
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

from apps.shared.events import BusinessEvent

log = structlog.get_logger("labase.shared.bus")

E = TypeVar("E")

# Field-name substrings that must never reach the log verbatim (e.g. UserCreated.access_token).
# Matched case-insensitively against each dataclass field's name.
_REDACT_SUBSTRINGS = ("token", "password", "secret")


def _loggable_payload(event: object) -> dict[str, Any]:
    if not dataclasses.is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in dataclasses.fields(event):
        value = getattr(event, f.name)
        if any(s in f.name.lower() for s in _REDACT_SUBSTRINGS):
            payload[f.name] = "***" if value is not None else None
        else:
            payload[f.name] = value
    return payload


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[[Any], Awaitable[object]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[object]]) -> None:
        self._subs[event_type].append(handler)

    async def emit(self, event: object) -> list[object]:
        """Run every handler for this event in order; propagate exceptions.

        Dispatch walks the event's MRO — handlers registered on the concrete type fire first
        (most specific), then handlers registered on any base class. This lets a single
        subscriber on a base (e.g. the business-events persister on ``BusinessEvent``) catch
        every subclass, while exact-type subscribers keep working unchanged. A handler
        registered on several classes in the MRO runs once.

        Every *non-business* event is logged here — a single, cheap trace point instead of each
        publisher remembering to log its own event (secret-shaped fields redacted by name). A
        ``BusinessEvent`` is skipped: the persister already records it durably to the trail with
        richer scoping (user/org/entity/request), and logging it too would surface the one action
        twice in the unified logs viewer — the technical `event.emitted` line beside its own trail
        row. The two systems stay visible side by side without overlapping on the same event.
        """
        if not isinstance(event, BusinessEvent):
            log.info("event.emitted", event_type=type(event).__name__, **_loggable_payload(event))
        # Command semantics: results are typed `object`, not `Any` — callers fire and discard
        # them. (`collect` keeps `Any`: its callers consume heterogeneous typed aggregates.)
        results: list[object] = []
        seen: set[int] = set()
        for klass in type(event).__mro__:
            for handler in self._subs.get(klass, ()):
                if id(handler) not in seen:
                    seen.add(id(handler))
                    results.append(await handler(event))
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
