"""One verdict for a background loop's failed tick (AGENTS: a failure that repeats is one bug).

For the lifespan workers (task queue, event listener, log drain, metrics flusher, capture drain),
which catch everything so one bad tick never ends the loop. They tick every second: an issue per
failed tick would bury the issues screen. A one-off failure (a task out of retries) logs its
exception directly instead.

Tracked per fault, not per outage: a second, different exception during an outage opens its own
issue. ``_fingerprint`` mirrors :func:`apps.issues.domain.service.fingerprint` without importing it:
``apps.shared`` names no context.
"""

from typing import Any


def _fingerprint(exc: BaseException) -> str:
    """Type and raise site: two ``RuntimeError`` from different lines are two faults."""
    frame = exc.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    if frame is None:
        return type(exc).__qualname__
    return f"{type(exc).__qualname__}@{frame.tb_frame.f_code.co_filename}:{frame.tb_lineno}"


class LoopHealth:
    """A loop's outage state, one instance per loop for the life of the process.

    ``name`` is the loop; the events derive from it: ``queue.worker`` → ``queue.worker_failed`` /
    ``queue.worker_recovered``.
    """

    def __init__(self, log: Any, name: str) -> None:
        self._log = log
        self._failed_event = f"{name}_failed"
        self._recovered_event = f"{name}_recovered"
        self._failures = 0
        self._opened_faults: set[str] = set()

    @property
    def failures(self) -> int:
        """Consecutive failing ticks, ``0`` when healthy."""
        return self._failures

    def tick_failed(self, exc: BaseException, **context: object) -> None:
        """A fault's first failure in an outage is an exception, later ones warnings, even when
        two faults alternate."""
        self._failures += 1
        fault = _fingerprint(exc)
        if fault in self._opened_faults:
            self._log.warning(self._failed_event, exc_info=exc, failures=self._failures, **context)
            return
        self._opened_faults.add(fault)
        if self._failures == 1:
            self._log.exception(self._failed_event, exc_info=exc, **context)
        else:
            self._log.exception(
                self._failed_event, exc_info=exc, failures=self._failures, **context
            )

    def tick_succeeded(self) -> None:
        """Silent, unless it ends an outage."""
        if self._failures:
            self._log.info(self._recovered_event, failures=self._failures)
            self._failures = 0
            self._opened_faults.clear()
