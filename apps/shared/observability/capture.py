"""The capture seam: every ``log.exception`` becomes a tracked issue.

Doctrine (three levels):

- ``log.info`` — expected/operational (a normal outcome; nothing is wrong).
- ``log.warning`` — degraded but manageable (something failed but was handled/retried).
- ``log.exception`` — a bug; captured here and folded into an error group by ``apps/issues``.

A structlog processor (:func:`capture_processor`, wired into the chain *before*
``format_exc_info`` so the live exception is still present) tees every ``log.exception`` call
into a bounded in-memory queue. A background :class:`CaptureDrain` — the ``MetricsFlusher``
lifespan-task shape — pops the queue and hands each exception to whoever tracks errors through
``events.notify(ExceptionCaptured)`` — the isolated (log-and-skip) fan-out, so a failing tracker
never worsens the error it tracks.

The processor never touches the event loop or the DB: ``log.exception`` can fire before the loop
exists (mount/startup) and from worker threads (auth's ``asyncio.to_thread`` GoTrue calls), so
enqueue is a plain ``deque.append`` (atomic under the GIL). All async/DB work lives in the drain.
"""

import asyncio
import contextlib
import sys
from collections import deque
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

from apps.shared.bus import events
from apps.shared.observability.errors import ExceptionCaptured

log = structlog.get_logger("labase.issues.capture")

# Bounded so that, when the issues app is disabled (no drain running), the queue self-caps by
# dropping the oldest instead of growing without limit.
_QUEUE: deque[ExceptionCaptured] = deque(maxlen=1000)

# Set while the drain is recording, so the capture path's own logs (``issue.recorded``, and
# ``events.notify``'s ``event.notify_handler_failed`` if a tracker handler fails) never re-enter.
_capturing: ContextVar[bool] = ContextVar("labase_capturing", default=False)

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
    unchanged so the firehose still renders the line for the logs viewer.

    The filtering bound logger routes ``.exception()`` through ``.error()`` with
    ``exc_info=True``, so the seam is "error level carrying an exception" — that is precisely
    ``log.exception`` (never a plain ``log.error``, which sets no ``exc_info``).
    """
    if method_name != "error" or _capturing.get():
        return event_dict
    exc = _exc_from(event_dict.get("exc_info"))
    if exc is None:
        return event_dict
    context = {
        k: v for k, v in event_dict.items() if k not in _DROP_KEYS and isinstance(v, _SCALARS)
    }
    # request_id/user_id/org_id (merged in by merge_contextvars) are the load-bearing keys the
    # unified logs viewer joins on; a coarse source stands in for the old "http"/"event_bus".
    context["source"] = "http" if context.get("request_id") else "app"
    _QUEUE.append(ExceptionCaptured(exc=exc, source=str(context["source"]), context=context))
    return event_dict


class CaptureDrain:
    """Lifespan task that folds queued exceptions into their error groups.

    Same shape as ``MetricsFlusher`` — idempotent ``start``, cancel-and-await ``stop``, and a
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

    async def tick(self) -> None:
        # Snapshot the current length so appends arriving mid-drain wait for the next tick.
        for _ in range(len(_QUEUE)):
            try:
                captured = _QUEUE.popleft()
            except IndexError:
                break
            token = _capturing.set(True)
            try:
                await events.notify(captured)  # log-and-skip semantics: never raises
            finally:
                _capturing.reset(token)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            try:
                await self.tick()
            except Exception:
                # A drain failure is degraded-but-manageable — and must NOT log.exception, which
                # would re-enter capture. Warn and retry next tick.
                log.warning("issues.capture_drain_failed")
