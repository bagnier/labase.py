"""The capture seam: every ``log.exception`` becomes a tracked issue
(AGENTS: a bug is an issue with a lifecycle).

A plain ``log.error`` is not captured: a site that means "this is a bug" raises and catches an
exception of its own to log (``UnroutableFact``, ``UnlimitedEndpoint``). A failure that repeats
goes through :mod:`apps.shared.logs.loop` instead.

:func:`capture_processor` sits in the chain and only appends to a bounded deque: it can run before
the event loop exists and from worker threads (auth's ``asyncio.to_thread`` GoTrue calls), so it
never touches the loop or the DB. :class:`CaptureDrain` hands each exception to the trackers
registered with :func:`on_captured` (``apps/issues``). Off the event bus: an exception is not a
business fact.

A capture no tracker took rejoins the back of the queue and ends the tick: a tracker that is
down is probed with one capture per tick, and the outage adds only the tracker's one failure.

Full, the queue sheds by fingerprint: a storm's own duplicates are evicted before any distinct
capture. Shedding takes more than one step, so the queue is guarded by a :class:`threading.Lock`.
"""

import asyncio
import contextlib
import sys
import threading
import traceback
from collections import Counter, deque
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


class CaptureQueueOverflowed(Exception):
    """Raised and caught at once so a drop folds into an issue of its own: a ``log.warning``
    would reach the log sink alone and age out of it."""


# Bounded: with the issues app disabled nothing drains it. Full, it sheds by fingerprint (see
# ``_shed``), not oldest first. Every read-check-mutate on it holds ``_lock``.
_QUEUE: deque[ExceptionCaptured] = deque(maxlen=1000)
_lock = threading.Lock()


@dataclass
class _Overflow:
    """Exceptions the full queue dropped. Reported by the drain: a line written from the
    processor would re-enter the chain."""

    dropped: int = 0


_overflow = _Overflow()


def _append(captured: ExceptionCaptured) -> None:
    """Append, shedding by fingerprint and counting when the queue is full. Shared by the
    processor and the drain's retry; it does not mark, since the retried exception is marked
    already."""
    with _lock:
        if len(_QUEUE) == _QUEUE.maxlen:
            _overflow.dropped += 1
            _shed()
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

# Stamped on an exception the first time its shedding key is computed — a storm's whole point is
# volume, so a key recomputed by walking the traceback on every later overflow would cost the
# request it is meant to protect. Not ``apps/issues``'s own fingerprint (richer, persisted,
# off-limits from here: shared never imports an app's domain) — only a cheap "same failure again"
# good enough to prefer shedding a duplicate over the one capture standing behind it.
_SHED_KEY = "_labase_shed_key"


def _shed_key(exc: BaseException) -> str:
    key = getattr(exc, _SHED_KEY, None)
    if key is not None:
        return key
    frames = traceback.extract_tb(exc.__traceback__)
    site = f"{frames[-1].filename}:{frames[-1].name}" if frames else ""
    key = f"{type(exc).__qualname__}|{site}"
    with contextlib.suppress(AttributeError, TypeError):
        setattr(exc, _SHED_KEY, key)
    return key


def _shed() -> None:
    """Make room in a full queue: evict a capture from whichever fingerprint currently repeats
    the most, so a storm's own duplicates pay for the room before any distinct capture does —
    whether or not the arriving exception shares that fingerprint. Falls back to the true oldest
    once every queued capture is already distinct from every other. Called with ``_lock`` held
    and the queue already at ``maxlen``, so there is always at least one entry to evict."""
    key, repeats = Counter(_shed_key(captured.exc) for captured in _QUEUE).most_common(1)[0]
    if repeats == 1:
        _QUEUE.popleft()
        return
    for captured in _QUEUE:
        if _shed_key(captured.exc) == key:
            _QUEUE.remove(captured)
            return


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
    # Warm the fingerprint cache now, spread over every capture as it arrives, so a storm's first
    # overflow never pays to walk a thousand tracebacks it should have already had cached.
    _shed_key(exc)
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
        with _lock:
            dropped, _overflow.dropped = _overflow.dropped, 0
        took_any = found_down = False
        # Snapshot the current length so appends arriving mid-drain wait for the next tick.
        for _ in range(len(_QUEUE)):
            with _lock:
                if not _QUEUE:
                    break
                captured = _QUEUE.popleft()
            if await self._deliver(captured):
                took_any = True
                continue
            # Postgres down is a tracker raising, not a capture that stops mattering: kept
            # for the next tick's retry rather than lost with the outage it would explain.
            # Through ``_append``, not ``_enqueue``: the exception carries its capture mark
            # already, so the marking path would read the retry as a duplicate and drop it.
            # Bound and shed like any other append: a concurrent request can fill the freed slot
            # while the tracker awaits, and the eviction that follows counts the same way.
            _append(captured)
            # And it ends the tick: what is still queued behind it would only cost the
            # tracker that is down one more failing call each, every tick of the outage.
            # Down only if nothing was taken: a tracker that took one is up and only refused
            # this capture.
            found_down = not took_any
            break
        if dropped and found_down:
            # The shortfall too: this tick's one probe is spent, so it waits for a tick that
            # finds the tracker back, with its count.
            with _lock:
                _overflow.dropped += dropped
        elif dropped:
            await self._report_overflow(dropped)

    async def _deliver(self, captured: ExceptionCaptured) -> bool:
        """Hand ``captured`` to every tracker, isolated; whether it is done with — taken by a
        tracker, or with no tracker subscribed to take it."""
        taken = False
        token = _capturing.set(True)
        try:
            for tracker in _trackers:
                try:
                    await tracker(captured)
                except BaseException as tracker_exc:
                    # Skip whatever a tracker raises, ``CancelledError`` included, except a real
                    # cancellation of this task: ``stop()`` would hang on it.
                    task = asyncio.current_task()
                    if (
                        isinstance(tracker_exc, asyncio.CancelledError)
                        and task is not None
                        and task.cancelling()
                    ):
                        raise
                    _report_tracker_failure(tracker, tracker_exc, captured.context)
                else:
                    taken = True
                    _report_tracker_recovery(tracker)
        finally:
            _capturing.reset(token)
        return taken or not _trackers

    async def _report_overflow(self, dropped: int) -> None:
        """Deliver the shortfall straight to the trackers, in this same tick, rather than
        enqueuing it for the next one: ``stop()`` runs exactly one tick before the process ends,
        and a storm's drop sitting one tick behind would die with it, unfolded.

        One no tracker took is kept like any such capture, but as its count rather than as a
        capture, and said only once taken: the report a tracker finally takes carries the whole
        shortfall, and the line says it once rather than on every tick of the outage."""
        try:
            raise CaptureQueueOverflowed(
                f"the capture queue shed {dropped} capture(s) it had no room for"
            )
        except CaptureQueueOverflowed as exc:
            if not await self._deliver(ExceptionCaptured(exc=exc, context={"dropped": dropped})):
                with _lock:
                    _overflow.dropped += dropped
                return
            token = _capturing.set(True)
            try:
                log.exception("capture.overflowed", exc_info=exc, dropped=dropped)
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
