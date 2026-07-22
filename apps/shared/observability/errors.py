"""The error-capture seam: the capture processor emits, whoever tracks errors subscribes.

Every ``log.exception`` is turned into an ``ExceptionCaptured`` by the structlog capture
processor (:mod:`apps.shared.observability.capture`) and fanned out by the capture drain to the
trackers registered there via ``on_captured`` — deliberately off the event bus, since this is
technical observability, not a persisted business fact. The drain's log-and-skip isolation IS the
capture doctrine: best-effort, never blocks, the error handler must never itself fail. Deleting
the issues context simply leaves the exception untracked.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExceptionCaptured:
    exc: BaseException
    source: str  # coarse origin: "http" (request-scoped) | "app"
    context: dict[str, Any] = field(default_factory=dict)
