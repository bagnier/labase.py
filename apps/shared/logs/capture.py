"""The capture seam: every ``log.exception`` becomes a tracked issue
(AGENTS: a bug is an issue with a lifecycle).

A plain ``log.error`` is not captured: a site that means "this is a bug" raises and catches an
exception of its own to log (``UnroutableFact``, ``UnlimitedEndpoint``). A failure that repeats
goes through :mod:`apps.shared.logs.loop` instead.

:func:`capture_processor` sits in the chain and only appends to a bounded deque: it can run before
the event loop exists and from worker threads (auth's ``asyncio.to_thread`` GoTrue calls), where a
``deque.append`` is still safe. :class:`CaptureDrain` hands each exception to the trackers
registered with :func:`on_captured` (``apps/issues``). Off the event bus: an exception is not a
business fact.

A capture no tracker took rejoins the back of the queue and ends the tick: a tracker that is
down is probed with one capture per tick, and the outage adds only the tracker's one failure.
"""

import asyncio
import contextlib
import sys
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from weakref import WeakKeyDictionary

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExceptionCaptured:
    """What the processor hands the drain: the live exception and what was true around it."""

    exc: BaseException
    context: dict[str, Any] = field(default_factory=dict)


# Bounded: with the issues app disabled nothing drains it, and the oldest are dropped.
_QUEUE: deque[ExceptionCaptured] = deque(maxlen=1000)


@dataclass
class _Overflow:
    """Exceptions the full queue dropped. Reported by the drain: a line written from the
    processor would re-enter the chain."""

    dropped: int = 0


_overflow = _Overflow()


def _append(captured: ExceptionCaptured) -> None:
    """Append, counting what a full queue sheds. Shared by the processor and the drain's retry;
    it does not mark, since the retried exception is marked already."""
    if len(_QUEUE) == _QUEUE.maxlen:
        _overflow.dropped += 1
    _QUEUE.append(captured)


# Set while the drain delivers, so a tracker's own logging is not captured again.
_capturing: ContextVar[bool] = ContextVar("labase_capturing", default=False)

ExceptionTracker = Callable[[ExceptionCaptured], Awaitable[None]]
_trackers: list[ExceptionTracker] = []

# Consecutive failures per tracker (AGENTS: a failure that repeats is one bug).
_tracker_failures: WeakKeyDictionary[ExceptionTracker, int] = WeakKeyDictionary()


def on_captured(tracker: ExceptionTracker) -> None:
    """Have the drain call ``tracker`` for each captured exception; its failures are isolated."""
    _trackers.append(tracker)


# Marks a queued exception so it is captured once: an unhandled 500 is logged by Starlette's 500
# handler, then again by the ASGI server it re-raises to. On the instance, not per type or message:
# two requests failing alike are two occurrences.
_CAPTURED = "_labase_captured"

_SCALARS = (str, int, float, bool, type(None))
# Render-noise keys that carry no correlation value into a stored issue.
_DROP_KEYS = frozenset({"exc_info", "exception", "timestamp", "level"})


def _exc_from(value: Any) -> BaseException | None:
    """The exception behind an unformatted ``exc_info``: ``True``, a ``sys.exc_info()`` tuple, or
    an instance."""
    if value is True:
        return sys.exc_info()[1]
    if isinstance(value, BaseException):
        return value
    if isinstance(value, tuple) and len(value) == 3:
        return value[1]
    return None


def _enqueue(exc: BaseException, context: dict[str, Any]) -> None:
    """Queue ``exc`` unless already captured. Bypasses the ``_capturing`` guard."""
    if getattr(exc, _CAPTURED, False):
        return
    # Some exceptions take no attribute; capture them anyway, at the risk of twice.
    with contextlib.suppress(AttributeError, TypeError):
        setattr(exc, _CAPTURED, True)
    _append(ExceptionCaptured(exc=exc, context=context))


def capture_processor(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Queue every ``log.exception`` and pass the line on unchanged.

    Must sit before ``format_exc_info``, which replaces the live exception with text. structlog
    routes ``.exception()`` to ``error`` with ``exc_info``, so that pair identifies it.
    """
    if method_name != "error" or _capturing.get():
        return event_dict
    exc = _exc_from(event_dict.get("exc_info"))
    if exc is None:
        return event_dict
    # Keeps request_id/user_id/org_id from the contextvars: the Timeline joins on them.
    context = {
        k: v for k, v in event_dict.items() if k not in _DROP_KEYS and isinstance(v, _SCALARS)
    }
    _enqueue(exc, context)
    return event_dict


def _report_tracker_failure(
    tracker: ExceptionTracker, tracker_exc: BaseException, context: dict[str, Any]
) -> None:
    """The first failure becomes an issue; the next ones only warn, or the tracker would requeue
    its own failure on every tick."""
    failures = _tracker_failures.get(tracker, 0) + 1
    _tracker_failures[tracker] = failures
    if failures == 1:
        log.exception("capture.tracker_failed", tracker=repr(tracker))
        _enqueue(tracker_exc, {**context, "tracker": repr(tracker)})
    else:
        log.warning(
            "capture.tracker_failed",
            exc_info=tracker_exc,
            tracker=repr(tracker),
            failures=failures,
        )


def _report_tracker_recovery(tracker: ExceptionTracker) -> None:
    if tracker in _tracker_failures:
        log.info(
            "capture.tracker_recovered",
            tracker=repr(tracker),
            failures=_tracker_failures.pop(tracker),
        )


async def drain_once() -> None:
    """Deliver the queue now, on the caller's task: for a lifespan startup that raised, before
    any drain started. A dying interpreter has no loop; :mod:`apps.shared.logs.chain` handles it.
    """
    drain = CaptureDrain(interval_seconds=0)
    await drain.tick()
    await drain.tick()  # delivers a tracker failure queued by the first tick


class CaptureDrain:
    """Lifespan task delivering queued exceptions; tests call ``tick`` with
    ``interval_seconds=0``."""

    def __init__(self, interval_seconds: float) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._interval > 0 and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self.tick()  # the exceptions before a restart explain it
        await self.tick()  # and a tracker failure queued by that tick

    async def tick(self) -> None:
        dropped, _overflow.dropped = _overflow.dropped, 0
        if dropped:
            log.warning("capture.overflowed", dropped=dropped)
        # Appends arriving mid-drain wait for the next tick.
        for _ in range(len(_QUEUE)):
            try:
                captured = _QUEUE.popleft()
            except IndexError:
                break
            token = _capturing.set(True)
            try:
                taken = False
                for tracker in _trackers:
                    try:
                        await tracker(captured)
                        taken = True
                    except BaseException as tracker_exc:
                        # Skip whatever a tracker raises, ``CancelledError`` included, except a
                        # real cancellation of this task: ``stop()`` would hang on it.
                        task = asyncio.current_task()
                        if (
                            isinstance(tracker_exc, asyncio.CancelledError)
                            and task is not None
                            and task.cancelling()
                        ):
                            raise
                        _report_tracker_failure(tracker, tracker_exc, captured.context)
                    else:
                        _report_tracker_recovery(tracker)
                if _trackers and not taken:
                    # Postgres down is a tracker raising, not a capture that stops mattering: kept
                    # for the next tick's retry rather than lost with the outage it would explain.
                    # Through ``_append``, not ``_enqueue``: the exception carries its capture mark
                    # already, so the marking path would read the retry as a duplicate and drop it.
                    # Bound like any other append: a concurrent request can fill the freed slot
                    # while the tracker awaits, and the eviction that follows counts the same way.
                    _append(captured)
                    # And it ends the tick: what is still queued behind it would only cost the
                    # tracker that is down one more failing call each, every tick of the outage.
                    break
            finally:
                _capturing.reset(token)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception as exc:
                # Not log.exception, which would re-enter capture; a warning still carries the
                # stack.
                log.warning("capture.drain_failed", exc_info=exc)
