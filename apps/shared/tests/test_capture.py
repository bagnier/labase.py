"""The capture seam's edges: what the full queue drops, one capture per exception, the drain at
shutdown, failing trackers. The round trip to the issues tables is in
``apps/issues/tests/test_capture.py``."""

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
    """Reported by the drain: a line from the processor would re-enter capture."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [])
    capture._overflow.dropped = 0

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    reported = [
        (line.name, line.payload) for line in log_chain() if line.logger == capture.__name__
    ]
    assert reported == [("capture.overflowed", {"dropped": 3})]


# An unhandled 500 is logged by Starlette's 500 handler, then again by the ASGI server.


def test_one_exception_is_one_capture_however_often_it_is_logged(log_chain):
    """Else every 500 would count two occurrences."""
    boom = RuntimeError("the request blew up")
    capture._QUEUE.clear()

    try:
        raise boom
    except RuntimeError:
        structlog.get_logger(_PROBE_LOGGER).exception("request.unhandled_error")
    logging.getLogger("hypercorn.error").error("Error in ASGI Framework", exc_info=boom)

    assert [captured.exc for captured in capture._QUEUE] == [boom]


def test_a_second_failure_of_the_same_kind_is_still_its_own_capture(log_chain):
    """The guard is per instance: two requests failing alike are two occurrences."""
    first, second = RuntimeError("blew up"), RuntimeError("blew up")
    capture._QUEUE.clear()
    log = structlog.get_logger(_PROBE_LOGGER)

    log.exception("request.unhandled_error", exc_info=first)
    log.exception("request.unhandled_error", exc_info=second)

    assert [captured.exc for captured in capture._QUEUE] == [first, second]


# Every deploy ends the process with SIGTERM: what the queue holds then must be delivered.


# A tracker raising ``CancelledError`` (a ``BaseException``) is skipped like any failing tracker.


@pytest.mark.asyncio
async def test_a_tracker_raising_cancelled_error_does_not_kill_the_drain(log_chain, monkeypatch):
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
    folded: list[capture.ExceptionCaptured] = []

    async def fold(captured: capture.ExceptionCaptured) -> None:
        folded.append(captured)

    # Not the real tracker, which would leave a cached engine bound to this loop.
    monkeypatch.setattr(capture, "_trackers", [fold])
    capture._QUEUE.clear()
    drain = capture.CaptureDrain(interval_seconds=0)
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("caught by the shutdown")
    )

    await drain.stop()

    assert [str(one.exc) for one in folded] == ["caught by the shutdown"]


@pytest.mark.asyncio
async def test_stopping_the_drain_still_cancels_it_mid_tracker(monkeypatch):
    """``stop()``'s real ``cancel()`` wins over the tracker isolation, or a deploy hangs on a
    tracker mid-flight."""
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
    # Not `asyncio.wait_for(drain.stop(), ...)`: `stop()` would swallow that timeout's
    # cancellation and return normally, a hang reading as a pass.
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


# The reentrancy guard must not hide a broken tracker: its failure is queued around the guard.


@pytest.mark.asyncio
async def test_a_failing_tracker_is_still_captured(log_chain, monkeypatch):
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))

    async def failing_tracker(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    monkeypatch.setattr(capture, "_trackers", [failing_tracker])
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("the original failure")
    )

    await capture.CaptureDrain(0).tick()

    assert [str(captured.exc) for captured in capture._QUEUE] == ["tracker itself is down"]


@pytest.mark.asyncio
async def test_a_failing_trackers_capture_keeps_the_original_correlation_keys(
    log_chain, monkeypatch
):
    """So the tracker's issue still leads back to its request."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    capture._tracker_failures.clear()

    async def failing_tracker(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    monkeypatch.setattr(capture, "_trackers", [failing_tracker])
    with structlog.contextvars.bound_contextvars(request_id="req-1"):
        structlog.get_logger(_PROBE_LOGGER).exception(
            "todo.blew_up", exc_info=RuntimeError("the original failure")
        )

    await capture.CaptureDrain(0).tick()

    assert capture._QUEUE[-1].context == {
        "event": "todo.blew_up",
        "logger": _PROBE_LOGGER,
        "request_id": "req-1",
        "tracker": repr(failing_tracker),
    }


# A tracker failing every tick is captured once. (AGENTS: a failure that repeats is one bug)


@pytest.mark.asyncio
async def test_a_permanently_broken_tracker_does_not_keep_the_queue_growing(log_chain, monkeypatch):
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    capture._tracker_failures.clear()

    async def failing_tracker(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    monkeypatch.setattr(capture, "_trackers", [failing_tracker])
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("the original failure")
    )

    for _ in range(5):
        await capture.CaptureDrain(0).tick()

    assert len(capture._QUEUE) == 0
    reported = [
        line.level
        for line in reversed(log_chain())  # oldest first
        if line.logger == capture.__name__ and line.name == "capture.tracker_failed"
    ]
    assert reported == ["error", "warning"]


@pytest.mark.asyncio
async def test_stopping_the_drain_also_folds_in_a_failing_trackers_own_failure(
    log_chain, monkeypatch
):
    """``stop`` ticks twice, so a tracker failing on the first is delivered too."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    capture._tracker_failures.clear()
    folded: list[str] = []

    async def failing_tracker(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    async def fold(captured: capture.ExceptionCaptured) -> None:
        folded.append(str(captured.exc))

    monkeypatch.setattr(capture, "_trackers", [failing_tracker, fold])
    drain = capture.CaptureDrain(interval_seconds=0)
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("caught by the shutdown")
    )

    await drain.stop()

    assert folded == ["caught by the shutdown", "tracker itself is down"]
