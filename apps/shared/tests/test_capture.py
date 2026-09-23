"""The seam's own edges — what it sheds, what it refuses to count twice, what it still owes.

``apps/issues/tests/test_capture.py`` covers the round trip all the way to the issues tables.
These hold what that round trip cannot state, all three about the *count* an issue carries:

- the queue is bounded so a storm can never eat memory, which means it drops — and a dropped
  capture is an issue nobody will ever see, so the shortfall is reported;
- one exception is one occurrence however many loggers see it on its way out;
- and the ones still queued when the process is asked to stop are folded in, not dropped.
"""

import asyncio
import logging
from collections import deque

import pytest
import structlog

from apps.shared.logs import capture

_PROBE_LOGGER = "apps.todo.infra.router"


def _log_exceptions(count: int) -> None:
    log = structlog.get_logger(_PROBE_LOGGER)
    for i in range(count):
        try:
            raise ValueError(f"storm {i}")
        except ValueError:
            log.exception("todo.blew_up")


@pytest.mark.asyncio
async def test_the_drain_reports_the_captures_the_queue_had_to_shed(log_chain, monkeypatch):
    """Silently dropping the oldest would lose the very exceptions the tracker exists to show,
    and the shortfall has to be said by the drain: the processor runs inside the logging chain,
    where a line of its own would re-enter capture."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [])  # the seam, not what issues does with it
    capture._overflow.dropped = 0

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    reported = [
        (line.name, line.payload) for line in log_chain() if line.logger == capture.__name__
    ]
    assert reported == [("capture.overflowed", {"dropped": 3})]


# An exception is logged more than once on its way out of the process, and the second logger is
# not ours. Starlette's ServerErrorMiddleware calls the 500 handler — which is the capture seam —
# and then *re-raises*, so the ASGI server catches the very same object and logs it again through
# stdlib `logging`, which the chain now joins. Two lines, one failure: measured on a real
# hypercorn server, a single unhandled 500 arrived here twice.


def test_one_exception_is_one_capture_however_often_it_is_logged(log_chain):
    """The seam counts failures, not the lines written about them: a second sighting of the same
    object is the same failure travelling, and folding it in again would double every 500's
    occurrence count — the one number an admin reads to judge how bad an issue is."""
    boom = RuntimeError("the request blew up")
    capture._QUEUE.clear()

    try:
        raise boom
    except RuntimeError:
        structlog.get_logger(_PROBE_LOGGER).exception("request.unhandled_error")
    logging.getLogger("hypercorn.error").error("Error in ASGI Framework", exc_info=boom)

    assert [captured.exc for captured in capture._QUEUE] == [boom]


def test_a_second_failure_of_the_same_kind_is_still_its_own_capture(log_chain):
    """The guard is per *instance*, never per type or per message — two requests failing the same
    way are two occurrences, which is exactly what an issue's count is for."""
    first, second = RuntimeError("blew up"), RuntimeError("blew up")
    capture._QUEUE.clear()
    log = structlog.get_logger(_PROBE_LOGGER)

    log.exception("request.unhandled_error", exc_info=first)
    log.exception("request.unhandled_error", exc_info=second)

    assert [captured.exc for captured in capture._QUEUE] == [first, second]


@pytest.mark.asyncio
async def test_a_capture_stays_queued_until_a_tracker_takes_it(monkeypatch):
    """Postgres going down mid-drain is a tracker raising, not a capture that stops mattering:
    the fingerprinting that would have turned it into an issue never ran, so the outage that
    explains itself has to survive to the tick where a tracker finally takes it — never lost
    with the very failure it would have opened an issue for."""
    attempts = 0

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [flaky])
    capture._QUEUE.clear()
    structlog.get_logger(_PROBE_LOGGER).exception("todo.blew_up", exc_info=RuntimeError("outage"))

    await capture.CaptureDrain(0).tick()
    assert len(capture._QUEUE) == 1, "no tracker took it yet, so it must stay queued"

    await capture.CaptureDrain(0).tick()
    assert (len(capture._QUEUE), attempts) == (0, 2)


@pytest.mark.asyncio
async def test_a_requeued_capture_reports_the_overflow_it_causes(monkeypatch):
    """A tracker's own await is exactly where a concurrent request can log its own failure and
    fill the one free slot: the re-append after a failed tracker meets a full queue like any
    other append, and the eviction that follows has to be counted the same way capture_processor
    counts one, or the overflow figure under-reports what the queue actually shed."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=1))
    capture._overflow.dropped = 0
    arrival = capture.ExceptionCaptured(exc=RuntimeError("arrived mid-drain"), context={})

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        capture._QUEUE.append(arrival)  # a concurrent request's own capture, mid-drain
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [flaky])
    outage = capture.ExceptionCaptured(exc=RuntimeError("outage"), context={})
    capture._QUEUE.append(outage)

    await capture.CaptureDrain(0).tick()

    assert capture._overflow.dropped == 1


@pytest.mark.asyncio
async def test_a_stayed_capture_rejoins_the_back_of_the_queue(monkeypatch):
    """The requeue is an ordinary append, not a jump back to the front: a capture whose tracker
    just failed waits behind whatever else is already queued, so a storm of failures still
    drains in the order it arrived instead of the same one spinning at the head forever."""
    seen: list[str] = []

    async def always_fails(captured: capture.ExceptionCaptured) -> None:
        seen.append(str(captured.exc))
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [always_fails])
    first = capture.ExceptionCaptured(exc=RuntimeError("first"))
    second = capture.ExceptionCaptured(exc=RuntimeError("second"))
    capture._QUEUE.clear()
    capture._QUEUE.extend([first, second])

    await capture.CaptureDrain(0).tick()

    assert seen == ["first", "second"]


# Shutdown is not a special case: SIGTERM is how every deploy ends a process, so whatever sits in
# the queue at that moment is the *normal* amount to lose, not an edge one. The log drain
# already emptied on its way out; this one dropped the exceptions it was holding.


# ``asyncio.CancelledError`` derives from ``BaseException``, not ``Exception`` — a tracker that
# raises it (its own bug, not the drain task being cancelled) must be log-and-skipped exactly
# like any other failing tracker, never left to abort the tick mid-queue.


@pytest.mark.asyncio
async def test_a_tracker_raising_cancelled_error_does_not_kill_the_drain(log_chain, monkeypatch):
    """A misbehaving tracker raising ``CancelledError`` must not worsen the exceptions queued
    after it: the doctrine (README: 'a failing tracker never worsens the exception it tracks')
    does not carve out ``BaseException`` subclasses."""
    tracked: list[capture.ExceptionCaptured] = []

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        raise asyncio.CancelledError

    async def fine(captured: capture.ExceptionCaptured) -> None:
        tracked.append(captured)

    monkeypatch.setattr(capture, "_trackers", [flaky, fine])
    monkeypatch.setattr(
        capture,
        "_QUEUE",
        deque(
            [
                capture.ExceptionCaptured(exc=ValueError("first")),
                capture.ExceptionCaptured(exc=ValueError("second")),
            ]
        ),
    )

    await capture.CaptureDrain(0).tick()

    assert [str(c.exc) for c in tracked] == ["first", "second"]


@pytest.mark.asyncio
async def test_a_tracker_raising_any_base_exception_does_not_kill_the_drain(monkeypatch):
    """The isolation is not a list of exception types to keep pace with: whatever a tracker
    raises — ``CancelledError`` is one case among the whole ``BaseException`` tree, not the
    only member of it — the rest of the queue must still be drained."""
    tracked: list[capture.ExceptionCaptured] = []

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        raise SystemExit("tracker bug")

    async def fine(captured: capture.ExceptionCaptured) -> None:
        tracked.append(captured)

    monkeypatch.setattr(capture, "_trackers", [flaky, fine])
    monkeypatch.setattr(
        capture,
        "_QUEUE",
        deque(
            [
                capture.ExceptionCaptured(exc=ValueError("first")),
                capture.ExceptionCaptured(exc=ValueError("second")),
            ]
        ),
    )

    await capture.CaptureDrain(0).tick()

    assert [str(c.exc) for c in tracked] == ["first", "second"]


@pytest.mark.asyncio
async def test_stopping_the_drain_folds_in_what_it_was_still_holding(log_chain, monkeypatch):
    """The last exceptions before a deploy are the ones most likely to explain it."""
    folded: list[capture.ExceptionCaptured] = []

    async def fold(captured: capture.ExceptionCaptured) -> None:
        folded.append(captured)

    # The seam, not what issues does with it — the real tracker would open a database session on
    # this test's loop and leave a cached engine bound to it.
    monkeypatch.setattr(capture, "_trackers", [fold])
    capture._QUEUE.clear()
    drain = capture.CaptureDrain(interval_seconds=0)  # never started: nothing ticks on its own
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("caught by the shutdown")
    )

    await drain.stop()

    assert [str(one.exc) for one in folded] == ["caught by the shutdown"]


@pytest.mark.asyncio
async def test_stopping_the_drain_still_cancels_it_mid_tracker(monkeypatch):
    """The guard that lets a tracker's own ``CancelledError`` through checks ``Task.cancelling()``
    precisely so that ``stop()``'s real ``cancel()`` — landing while the drain happens to be
    suspended inside a tracker's own await — still wins: otherwise every deploy would hang on
    whichever tracker was mid-flight."""
    started = asyncio.Event()

    async def stuck(_captured: capture.ExceptionCaptured) -> None:
        started.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(capture, "_trackers", [stuck])
    capture._QUEUE.clear()
    capture._QUEUE.append(capture.ExceptionCaptured(exc=ValueError("boom")))
    drain = capture.CaptureDrain(interval_seconds=0.01)
    await drain.start()
    task = drain._task
    assert task is not None

    await asyncio.wait_for(started.wait(), timeout=1)
    # Not `asyncio.wait_for(drain.stop(), ...)`: its own timeout would cancel `stop()` itself,
    # and `stop()`'s `contextlib.suppress(CancelledError)` around `await self._task` would
    # swallow that unrelated cancellation too, letting `stop()` return normally regardless of
    # whether the background task ever actually ended — a hang that reads as a pass.
    stop_task = asyncio.ensure_future(drain.stop())
    try:
        done, _pending = await asyncio.wait({stop_task}, timeout=1)
        assert stop_task in done, "stop() must not hang on a tracker stuck mid-await"
    finally:
        if not stop_task.done():
            stop_task.cancel()
        if not task.done():
            task.cancel()

    assert task.cancelled()
