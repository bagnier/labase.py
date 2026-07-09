"""The error-capture seam: the capture processor emits, whoever tracks errors subscribes.

Every ``log.exception`` is turned into an ``ExceptionCaptured`` by the structlog capture
processor (:mod:`apps.shared.observability.capture`) and drained through ``EventBus.collect`` —
its log-and-skip semantics ARE the capture doctrine: best-effort, never blocks, the error
handler must never itself fail. Deleting the issues context simply leaves the event unanswered.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExceptionCaptured:
    exc: BaseException
    source: str  # coarse origin: "http" (request-scoped) | "app"
    context: dict[str, Any] = field(default_factory=dict)
