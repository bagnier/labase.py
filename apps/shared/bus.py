"""Type-keyed async event bus — the generic pub/sub mechanism every context wires into.

Two primitives:

- ``emit(event)`` — push/command: run all handlers, propagate the first exception (caller
  can compensate), return their results.
- ``collect(query)`` — pull/query: run all handlers, isolate failures (log + skip), return
  successful results.
"""

import dataclasses
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

import structlog

from apps.shared.observability.errors import ExceptionCaptured, capture_context

log = structlog.get_logger("labase.shared.bus")

E = TypeVar("E")

# Field-name substrings that must never reach the log verbatim (e.g. UserCreated.access_token,
# OrgCreated.access_token). Matched case-insensitively against each dataclass field's name.
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
        self._subs: dict[type, list[Callable[..., Awaitable[Any]]]] = defaultdict(list)

    def on(self, event_type: type[E], handler: Callable[[E], Awaitable[Any]]) -> None:
        self._subs[event_type].append(handler)

    async def emit(self, event: object) -> list[Any]:
        """Run every handler for this event type in order; propagate exceptions.

        Every emitted event is logged here — a single, cheap trace point instead of each
        publisher remembering to log its own event. Secret-shaped fields are redacted by name.
        """
        log.info("event.emitted", event_type=type(event).__name__, **_loggable_payload(event))
        return [await handler(event) for handler in self._subs[type(event)]]

    async def collect(self, query: object) -> list[Any]:
        """Run every handler for this query type; log and skip failing handlers."""
        results: list[Any] = []
        for handler in self._subs[type(query)]:
            try:
                results.append(await handler(query))
            except Exception as exc:
                log.exception("query.handler_failed", handler=repr(handler))
                # Feed the error tracker — but never capture the capturers.
                if not isinstance(query, ExceptionCaptured):
                    await self.collect(
                        ExceptionCaptured(
                            exc,
                            source="event_bus",
                            context=capture_context(
                                event=type(query).__name__, handler=repr(handler)
                            ),
                        )
                    )
        return results
