"""The capture seam: every ``log.exception`` becomes a tracked issue.

Which calls earn a line at all, and at which level, is settled once (AGENTS: A line says what
no other record says):
two levels and this seam, no debug tier, and a bare ``log.error`` deliberately not the seam. What
that leaves to decide *here* is the question at the call site — never "should this be logged?" but
"what would a reader learn that neither the exchange nor the journal already tells them?".

The consequence is a trap worth naming: a site that means "this is a bug" and writes ``log.error``
gets a log line that rolls out of its window and nothing else. Such a site raises an
exception of its own to be seen — ``UnroutableFact`` in the event listener, ``UnlimitedEndpoint``
in the rate limiter — caught immediately, purely so the seam has something to fingerprint on. The
journal's write path is the deliberate exception to that: ``MaskedSecret`` is raised and caught the
same way, but reported through ``log.warning``, because the fact it describes already committed
once — folding it into an issue too would show it a second time (AGENTS: `emit` logs nothing of
its own). And a failure that *repeats* (a background loop, a readiness probe) goes through
:mod:`apps.shared.logs.loop` instead, which files the transition and not every tick.

A structlog processor (:func:`capture_processor`, wired into the chain *before*
``format_exc_info`` so the live exception is still present) tees every ``log.exception`` call
into a bounded in-memory queue. A background :class:`CaptureDrain` — the ``MetricsFlusher``
lifespan-task shape — pops the queue and hands each one to whoever tracks exceptions. Trackers
register directly here via :func:`on_captured` (``apps/issues`` subscribes its own at mount);
the drain fans each exception out to them with log-and-skip isolation, so a failing tracker never
worsens the exception it tracks. That isolation IS the doctrine: best-effort, never blocking, and a
tracker that must never itself fail — so deleting the issues context simply leaves the exception
untracked. A tracker that starts failing is itself queued, once, on the tick after the one that
found it broken — so a broken tracker becomes its own issue rather than a silent gap — and stays a
warning for as long as it keeps failing, the same transition-not-tick verdict
:mod:`apps.shared.logs.loop` holds for the other lifespan workers. A capture no tracker took is not
lost with the outage it would explain: it rejoins the back of the queue and ends the tick, so for as
long as the tracker stays down each tick probes it with one capture rather than the whole queue, and
the outage adds nothing to the queue of its own but the tracker's one failure. The seam is
deliberately off the event bus: an ``ExceptionCaptured`` is technical observability, not a
persisted business fact.

The processor never touches the event loop or the DB: ``log.exception`` can fire before the loop
exists (mount/startup) and from worker threads (auth's ``asyncio.to_thread`` GoTrue calls), so the
queue is guarded by a plain :class:`threading.Lock` rather than relying on a single GIL-atomic
call — shedding by fingerprint takes more than one step, and two threads racing that step is
exactly the storm scenario this module exists to survive. All async/DB work lives in the drain.
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
    """A dropped capture is an issue nobody would otherwise see: ``log.warning`` reaches the log
    sink and nothing else, and rolls out of its window with no trace — no other record says this
    one (AGENTS: A line says what no other record says). Raised only to give the drop itself
    something to fold into an issue, exactly like the listener's ``UnroutableFact`` or the rate
    limiter's ``UnlimitedEndpoint`` — caught immediately, purely so the seam has a live exception
    to fingerprint on."""


# Bounded so that with the issues app disabled — no drain running — the queue self-caps instead of
# growing without limit. Full, it sheds by fingerprint (see ``_shed``) rather than the deque's own
# blind oldest-first eviction, so a storm of identical failures never costs a distinct one queued
# behind it. Every read-check-mutate sequence against it holds ``_lock``.
_QUEUE: deque[ExceptionCaptured] = deque(maxlen=1000)
_lock = threading.Lock()


@dataclass
class _Overflow:
    """What the bounded queue shed before any drain could take it — an exception nobody will
    ever see. Counted here and reported by the drain, because the processor runs inside the
    logging chain, where a line of its own would re-enter capture."""

    dropped: int = 0


_overflow = _Overflow()


def _append(captured: ExceptionCaptured) -> None:
    """Append to the bounded queue, shedding by fingerprint when it is full and counting the
    eviction — shared by the processor's own capture and the drain's retry, an ordinary append
    either way. It does not mark: the retry re-queues a capture whose exception ``_enqueue``
    marked already."""
    with _lock:
        if len(_QUEUE) == _QUEUE.maxlen:
            _overflow.dropped += 1
            _shed()
        _QUEUE.append(captured)


# Set while the drain is delivering, so a tracker's own ordinary logging never re-enters the
# capture processor mid-drain. ``capture.tracker_failed`` is logged under the same guard, but the
# exception behind a tracker's *first* failure is queued directly (see ``tick``), past the guard.
_capturing: ContextVar[bool] = ContextVar("labase_capturing", default=False)

# An exception tracker, registered directly at mount by whoever tracks them (``apps/issues``) rather
# than through the event bus — the drain fans each captured exception out to them. One event type
# only, hence a plain list and no MRO or type-key dispatch.
ExceptionTracker = Callable[[ExceptionCaptured], Awaitable[None]]
_trackers: list[ExceptionTracker] = []

# Consecutive failures per tracker (AGENTS: a failure that repeats is one bug) — the level a
# failure earns, and whether it is queued at all, follows the *transition* into and out of it,
# not the tick. Weak-keyed so a tracker no longer subscribed is not held here for nothing.
_tracker_failures: WeakKeyDictionary[ExceptionTracker, int] = WeakKeyDictionary()


def on_captured(tracker: ExceptionTracker) -> None:
    """Subscribe ``tracker`` to captured exceptions — the drain calls it per exception, isolated."""
    _trackers.append(tracker)


# Stamped on an exception the moment it is queued, so the *same failure* is never folded in
# twice. It is logged more than once on its way out: Starlette's ServerErrorMiddleware calls the
# 500 handler — this seam — and then re-raises, so the ASGI server catches the very same object
# and logs it again through stdlib ``logging``, which the chain now joins. Measured on a real
# hypercorn server, one unhandled 500 reached here twice.
#
# The mark rides the instance rather than a set of seen exceptions: nothing to size, nothing to
# evict, and it dies with the object. Per instance and not per type or message, because two
# requests failing the same way *are* two occurrences — that count is what an issue is for.
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
    """The live exception behind a structlog ``exc_info`` value.

    ``log.exception`` sets ``exc_info=True``; before ``format_exc_info`` runs it is still the
    raw value passed to the call — ``True`` (resolve via ``sys.exc_info()``), a ``(type, exc,
    tb)`` tuple, or an exception instance. A falsy value means "not an exception log".
    """
    if value is True:
        return sys.exc_info()[1]
    if isinstance(value, BaseException):
        return value
    if isinstance(value, tuple) and len(value) == 3:
        return value[1]
    return None


def _enqueue(exc: BaseException, context: dict[str, Any]) -> None:
    """Mark ``exc`` captured and append it, bounded — the part ``capture_processor`` and a
    failing tracker's own capture (below) both need, the latter reached straight past the
    ``_capturing`` guard that would otherwise swallow it."""
    if getattr(exc, _CAPTURED, False):
        return
    # A C-level or ``__slots__`` exception takes no marks; capture it anyway, at the risk of twice.
    with contextlib.suppress(AttributeError, TypeError):
        setattr(exc, _CAPTURED, True)
    # Warm the fingerprint cache now, spread over every capture as it arrives, so a storm's first
    # overflow never pays to walk a thousand tracebacks it should have already had cached.
    _shed_key(exc)
    _append(ExceptionCaptured(exc=exc, context=context))


def capture_processor(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: enqueue every ``log.exception`` for capture, pass the event through.

    Must sit before ``format_exc_info`` (needs the live exception) and returns ``event_dict``
    unchanged so the sink still records the line for the logs viewer — every line is written,
    including the second one about an exception already captured; only the *issue* is deduped.

    The filtering bound logger routes ``.exception()`` through ``.error()`` with
    ``exc_info=True``, so the seam is "error level carrying an exception" — that is precisely
    ``log.exception`` (never a plain ``log.error``, which sets no ``exc_info``).
    """
    if method_name != "error" or _capturing.get():
        return event_dict
    exc = _exc_from(event_dict.get("exc_info"))
    if exc is None:
        return event_dict
    # request_id/user_id/org_id (merged in by merge_contextvars) are the load-bearing keys the
    # timeline joins on — and whether a request was in flight is read off request_id itself.
    context = {
        k: v for k, v in event_dict.items() if k not in _DROP_KEYS and isinstance(v, _SCALARS)
    }
    _enqueue(exc, context)
    return event_dict


def _report_tracker_failure(
    tracker: ExceptionTracker, tracker_exc: BaseException, context: dict[str, Any]
) -> None:
    """The level follows the *transition*: the first failure is queued (past the ``_capturing``
    guard, which would otherwise swallow it) so a broken tracker becomes its own issue; a tracker
    already known broken only warns, or every tick would re-enqueue its own failure and the queue
    would never settle."""
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
    """Fold whatever is queued into its issues, now, on the caller's task.

    For the one moment there is still an event loop but no drain running: a lifespan startup that
    raised. The trackers subscribe at *mount*, so they are already there; only the background task
    that would have emptied the queue never started, and the process is about to die with the
    exception that explains why still sitting in it.

    Not the answer for a dying interpreter — ``sys.excepthook`` runs with no loop and no pool, and
    writes its line to disk instead (see :mod:`apps.shared.logs.chain`).
    """
    drain = CaptureDrain(interval_seconds=0)
    await drain.tick()
    await drain.tick()  # a tracker's own failure on that first tick is queued for this one


class CaptureDrain:
    """Lifespan task that folds queued exceptions into their issues.

    Same shape as ``MetricsFlusher`` — idempotent ``start``, cancel-and-drain ``stop``, and a
    ``tick`` that tests drive by hand with ``interval_seconds=0``.
    """

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
        await self.tick()  # the exceptions before a restart are the ones that explain it
        await self.tick()  # and a tracker failing on that tick queued its own failure too

    async def tick(self) -> None:
        with _lock:
            dropped, _overflow.dropped = _overflow.dropped, 0
        # Snapshot the current length so appends arriving mid-drain wait for the next tick.
        for _ in range(len(_QUEUE)):
            with _lock:
                if not _QUEUE:
                    break
                captured = _QUEUE.popleft()
            if not await self._deliver(captured):
                # Postgres down is a tracker raising, not a capture that stops mattering: kept
                # for the next tick's retry rather than lost with the outage it would explain.
                # Through ``_append``, not ``_enqueue``: the exception carries its capture mark
                # already, so the marking path would read the retry as a duplicate and drop it.
                # Bound and shed like any other append: a concurrent request can fill the freed slot
                # while the tracker awaits, and the eviction that follows counts the same way.
                _append(captured)
                # And it ends the tick: what is still queued behind it would only cost the
                # tracker that is down one more failing call each, every tick of the outage.
                break
        if dropped:
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
                    # Log-and-skip: a failing tracker must never worsen the exception it
                    # tracks, nor abort the others — whatever it raises, ``CancelledError``
                    # included. The one carve-out is a *real* cancellation of this task
                    # (``Task.cancelling()`` counts ``cancel()`` calls still pending): that one
                    # must still unwind the drain, or ``stop()`` hangs forever on a tracker
                    # that outlives it.
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
                # A drain failure is degraded-but-manageable — and must NOT log.exception, which
                # would re-enter capture. Warn and retry next tick. ``exc_info`` on a *warning* is
                # how the stack still reaches the log sink: the seam only fires at ``error``.
                log.warning("capture.drain_failed", exc_info=exc)
