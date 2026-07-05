"""The error-capture seam: shared emits, whoever tracks errors subscribes.

Shared code (500 handler, event bus) publishes ``ExceptionCaptured`` through
``EventBus.collect`` — its log-and-skip semantics ARE the capture doctrine:
best-effort, never blocks, the error handler must never itself fail. Deleting
the issues context simply leaves the event unanswered.
"""

import contextlib
from dataclasses import dataclass, field
from typing import Any

import structlog


@dataclass(frozen=True)
class ExceptionCaptured:
    exc: BaseException
    source: str  # "http" | "event_bus"
    context: dict[str, Any] = field(default_factory=dict)


def capture_context(**extra: Any) -> dict[str, Any]:
    """Request correlation for an event: the bound request_id pivots each stored
    error to its structlog lines."""
    ctx: dict[str, Any] = {}
    with contextlib.suppress(Exception):
        ctx.update(structlog.contextvars.get_contextvars())
    ctx.update(extra)
    return {k: v for k, v in ctx.items() if isinstance(v, str | int | float | bool | type(None))}
