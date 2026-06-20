"""Type-keyed async event bus — the generic pub/sub mechanism every context wires into.

Two primitives:

- ``emit(event)`` — push/command: run all handlers, propagate the first exception (caller
  can compensate), return their results.
- ``collect(query)`` — pull/query: run all handlers, isolate failures (log + skip), return
  successful results.
"""

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

_log = logging.getLogger(__name__)

E = TypeVar("E")


class EventBus:
    """Type-keyed async pub/sub. Handlers are dispatched by the event's runtime type."""

    def __init__(self) -> None:
        self._subs: dict[type, list[Callable[..., Awaitable[Any]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[Any]]) -> None:
        self._subs[event_type].append(handler)

    async def emit(self, event: object) -> list[Any]:
        """Run every handler for this event type in order; propagate exceptions."""
        return [await handler(event) for handler in self._subs[type(event)]]

    async def collect(self, query: object) -> list[Any]:
        """Run every handler for this query type; log and skip failing handlers."""
        results: list[Any] = []
        for handler in self._subs[type(query)]:
            try:
                results.append(await handler(query))
            except Exception:
                _log.exception("query handler %r failed; skipping", handler)
        return results
