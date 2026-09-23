"""One verdict for a background loop whose tick failed: a blip, or the machinery is down.

The twin of :mod:`apps.shared.logs.dependency`, which judges a failed call *out* of the
process. This one judges a failed tick *inside* it — the five lifespan workers (task queue, event
listener, log drain, metrics flusher, capture drain), which by construction catch everything
so that one bad tick never ends the loop.

Which level a failing tick earns is settled once (AGENTS: a failure that repeats is one bug):
the level
follows the *transition*, not the tick — the same shape as the log sink's own ``_Outage``. The
arithmetic is what forced it: these loops tick once a second, so promoting every failed tick to
``log.exception`` would file one issue eighty-six thousand times a day and bury the screen it was
meant to raise the alarm on.

A failure that is *not* a loop — a queued task exhausting its retries, a spread handler refusing a
config reload — is a defect of its own and logs at ``exception`` directly. This is only for what
repeats.

The transition is tracked per *fault*, not per outage: a second, distinct exception arriving
mid-outage is a bug of its own and earns its own opening line — folding it into the first
fault's warnings is how it never reaches the issues screen at all. ``_fingerprint`` keys a
fault the same way :func:`apps.issues.domain.service.fingerprint` keys an issue — type plus
raise site — deliberately not by importing it: ``apps.shared`` names no bounded context.
"""

from typing import Any


def _fingerprint(exc: BaseException) -> str:
    """The type plus where it was raised — two different bugs sharing a built-in type (a
    ``RuntimeError`` from the claim query, one from the commit after it) are not one fault."""
    frame = exc.__traceback__
    while frame is not None and frame.tb_next is not None:
        frame = frame.tb_next
    if frame is None:
        return type(exc).__qualname__
    return f"{type(exc).__qualname__}@{frame.tb_frame.f_code.co_filename}:{frame.tb_lineno}"


class LoopHealth:
    """Whether a background loop's tick is currently failing, and how it is allowed to say so.

    ``name`` is the loop, not the line: the two event names are derived from it
    (``queue.worker`` → ``queue.worker_failed`` / ``queue.worker_recovered``), so a caller cannot
    spell a failure under one name and its recovery under another. One instance per loop, held by
    the worker for the life of the process — the state *is* "has this loop been failing".
    """

    def __init__(self, log: Any, name: str) -> None:
        self._log = log
        self._failed_event = f"{name}_failed"
        self._recovered_event = f"{name}_recovered"
        self._failures = 0
        self._opened_faults: set[str] = set()

    @property
    def failures(self) -> int:
        """Consecutive failing ticks — ``0`` when healthy. What the loop already knows, said out
        loud so a screen can render it without a second source of truth."""
        return self._failures

    def tick_failed(self, exc: BaseException, **context: object) -> None:
        """Record a tick that raised, at the level its place in the outage warrants.

        A fault already opened this outage keeps warning, however many ticks it has run for —
        two faults taking turns tick to tick must not reopen each other every time, which is the
        same flood this module exists to avoid, just spread over two exception types."""
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
        """Record a tick that returned. Says nothing unless it ends an outage — a healthy loop
        writing a line per tick is exactly the volume this module exists to avoid."""
        if self._failures:
            self._log.info(self._recovered_event, failures=self._failures)
            self._failures = 0
            self._opened_faults.clear()
