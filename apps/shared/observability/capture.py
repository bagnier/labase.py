"""The capture seam: every ``log.exception`` becomes a tracked issue.

Doctrine (three levels):

- ``log.info`` — expected/operational (a normal outcome; nothing is wrong).
- ``log.warning`` — degraded but manageable (something failed but was handled/retried).
- ``log.exception`` — a bug; captured here and folded into an issue by ``apps/issues``.

A bare ``log.error`` — ``error`` level carrying no exception — is deliberately **not** the seam,
and that is not an oversight: ``request.finished`` is written at ``error`` on every 5xx to state
the *outcome* of the exchange, while the exception itself is captured once by the 500 handler.
Opening an issue on level alone would double every 500.

The consequence is a trap worth naming: a site that means "this is a bug" and writes ``log.error``
gets a firehose line that rolls out of its window and nothing else. Such a site raises an
exception of its own to be seen — ``UnroutableFact`` in the event listener, ``UnlimitedEndpoint``
in the rate limiter, ``MaskedSecret`` on the journal's write path — caught immediately, purely so
the seam has something to fingerprint on. And a failure that *repeats* (a background loop, a
readiness probe) goes through :mod:`apps.shared.observability.loop` instead, which files the
transition and not every tick.

A structlog processor (:func:`capture_processor`, wired into the chain *before*
``format_exc_info`` so the live exception is still present) tees every ``log.exception`` call
into a bounded in-memory queue. A background :class:`CaptureDrain` — the ``MetricsFlusher``
lifespan-task shape — pops the queue and hands each one to whoever tracks exceptions. Trackers
register directly here via :func:`on_captured` (``apps/issues`` subscribes its own at mount);
the drain fans each exception out to them with log-and-skip isolation, so a failing tracker never
worsens the exception it tracks. That isolation IS the doctrine: best-effort, never blocking, and a
tracker that must never itself fail — so deleting the issues context simply leaves the exception
untracked. The seam is deliberately off the event bus: an ``ExceptionCaptured`` is technical
observability, not a persisted business fact.

The processor never touches the event loop or the DB: ``log.exception`` can fire before the loop
exists (mount/startup) and from worker threads (auth's ``asyncio.to_thread`` GoTrue calls), so
enqueue is a plain ``deque.append`` (atomic under the GIL). All async/DB work lives in the drain.
"""

import asyncio
import contextlib
import sys
from collections import deque
from collections.abc import Awaitable, Callable, MutableMapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class ExceptionCaptured:
    """What the processor hands the drain: the live exception and what was true around it."""

    exc: BaseException
    context: dict[str, Any] = field(default_factory=dict)


# Bounded so that with the issues app disabled — no drain running — the queue self-caps by dropping
# the oldest instead of growing without limit.
_QUEUE: deque[ExceptionCaptured] = deque(maxlen=1000)


@dataclass
class _Overflow:
    """What the bounded queue shed before any drain could take it — an exception nobody will
    ever see. Counted here and reported by the drain, because the processor runs inside the
    logging chain, where a line of its own would re-enter capture."""

    dropped: int = 0


_overflow = _Overflow()

# Set while the drain is delivering, so the capture path's own logs — a tracker's, and
# ``capture.tracker_failed`` when one raises — never re-enter the capture processor.
_capturing: ContextVar[bool] = ContextVar("labase_capturing", default=False)

# An exception tracker, registered directly at mount by whoever tracks them (``apps/issues``) rather
# than through the event bus — the drain fans each captured exception out to them. One event type
# only, hence a plain list and no MRO or type-key dispatch.
ExceptionTracker = Callable[[ExceptionCaptured], Awaitable[None]]
_trackers: list[ExceptionTracker] = []


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


def capture_processor(
    _logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """structlog processor: enqueue every ``log.exception`` for capture, pass the event through.

    Must sit before ``format_exc_info`` (needs the live exception) and returns ``event_dict``
    unchanged so the firehose still renders the line for the logs viewer — every line is written,
    including the second one about an exception already captured; only the *issue* is deduped.

    The filtering bound logger routes ``.exception()`` through ``.error()`` with
    ``exc_info=True``, so the seam is "error level carrying an exception" — that is precisely
    ``log.exception`` (never a plain ``log.error``, which sets no ``exc_info``).
    """
    if method_name != "error" or _capturing.get():
        return event_dict
    exc = _exc_from(event_dict.get("exc_info"))
    if exc is None or getattr(exc, _CAPTURED, False):
        return event_dict
    # A C-level or ``__slots__`` exception takes no marks; capture it anyway, at the risk of twice.
    with contextlib.suppress(AttributeError, TypeError):
        setattr(exc, _CAPTURED, True)
    # request_id/user_id/org_id (merged in by merge_contextvars) are the load-bearing keys the
    # timeline joins on — and whether a request was in flight is read off request_id itself.
    context = {
        k: v for k, v in event_dict.items() if k not in _DROP_KEYS and isinstance(v, _SCALARS)
    }
    if len(_QUEUE) == _QUEUE.maxlen:
        _overflow.dropped += 1
    _QUEUE.append(ExceptionCaptured(exc=exc, context=context))
    return event_dict


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

    async def tick(self) -> None:
        dropped, _overflow.dropped = _overflow.dropped, 0
        if dropped:
            log.warning("capture.overflowed", dropped=dropped)
        # Snapshot the current length so appends arriving mid-drain wait for the next tick.
        for _ in range(len(_QUEUE)):
            try:
                captured = _QUEUE.popleft()
            except IndexError:
                break
            token = _capturing.set(True)
            try:
                for tracker in _trackers:
                    try:
                        await tracker(captured)
                    except Exception:
                        # Log-and-skip: a failing tracker must never worsen the exception it tracks,
                        # nor abort the others. Logged under the guard, so it does not re-capture.
                        log.exception("capture.tracker_failed", tracker=repr(tracker))
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
                # how the stack still reaches the firehose: the seam only fires at ``error``.
                log.warning("capture.drain_failed", exc_info=exc)
