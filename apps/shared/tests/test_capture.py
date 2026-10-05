"""The capture seam's edges: what the full queue sheds and reports, one capture per exception, the
drain at shutdown, failing trackers. The round trip to the issues tables is in
``apps/issues/tests/test_capture.py``."""

import asyncio
import logging
from collections import deque
from datetime import UTC, datetime, timedelta
from weakref import WeakKeyDictionary

import pytest
import structlog

from apps.shared import clock
from apps.shared.logs import capture
from apps.shared.settings.env import get_technical_settings

_PROBE_LOGGER = "apps.todo.infra.router"


@pytest.fixture(autouse=True)
def _reset_overflow_counter():
    """A leftover count from another test would otherwise ride into this one's own ``tick()`` —
    now delivered straight to whatever tracker is wired up, not just a log line to skim past. The
    retry state must go with it: a stale ``owed_to`` naming a previous test's tracker object would
    read as "already taken" for a tracker this test never registered."""
    capture._overflow.dropped = 0
    capture._overflow.retry = capture._Retry()
    yield
    capture._overflow.dropped = 0
    capture._overflow.retry = capture._Retry()


def _log_exceptions(count: int) -> None:
    log = structlog.get_logger(_PROBE_LOGGER)
    for i in range(count):
        try:
            raise ValueError(f"storm {i}")
        except ValueError:
            log.exception("todo.blew_up")


def test_a_storm_of_duplicates_never_evicts_the_distinct_capture_behind_it(monkeypatch):
    """A blind FIFO eviction costs whatever sits at the front of the queue, storm or not — a
    cheap 500 repeated a thousand times would then evict the one distinct failure that arrived
    first. Shedding by fingerprint instead means the storm pays for its own room: three slots let
    the distinct capture and two of the storm's coexist, so the third can crowd its own kind out
    rather than the one thing standing apart from it."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=3))
    log = structlog.get_logger(_PROBE_LOGGER)
    try:
        raise KeyError("distinct")
    except KeyError:
        log.exception("todo.blew_up")

    _log_exceptions(5)

    assert [type(captured.exc) for captured in capture._QUEUE] == [
        KeyError,
        ValueError,
        ValueError,
    ]


@pytest.mark.asyncio
async def test_the_drain_reports_the_captures_the_queue_had_to_shed(log_chain, monkeypatch):
    """Reported by the drain: a line from the processor would re-enter capture."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [])
    capture._overflow.dropped = 0

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    [reported] = [line for line in log_chain() if line.logger == capture.__name__]
    assert (reported.name, reported.payload["dropped"]) == ("capture.overflowed", 3)


@pytest.mark.asyncio
async def test_the_dropped_shortfall_reaches_the_trackers_the_same_tick(monkeypatch):
    """A warning that ages out of the two-day log window leaves nothing an admin can find
    tomorrow (AGENTS: A line says what no other record says) — the shortfall must instead reach
    the trackers directly, the same tick it is counted, so even the single tick ``stop()`` runs
    before a deploy still folds it into an issue rather than queuing it for a tick that never
    comes."""
    folded: list[capture.ExceptionCaptured] = []

    async def fold(captured: capture.ExceptionCaptured) -> None:
        folded.append(captured)

    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [fold])

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    delivered = [(type(c.exc), c.context.get("dropped")) for c in folded]
    assert delivered == [
        (ValueError, None),
        (ValueError, None),
        (capture.CaptureQueueOverflowed, 3),
    ]


@pytest.mark.asyncio
async def test_a_shortfall_no_tracker_took_is_reported_once_the_tracker_is_back(monkeypatch):
    """A queue overflows during an outage, which is exactly when the tracker is down: the
    shortfall is kept like any capture no tracker took, and its count is the one it reports once
    a tracker takes it."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    capture._overflow.dropped = 3
    calls = 0
    took: list[tuple[type[BaseException], object]] = []

    async def down_on_its_first_call(captured: capture.ExceptionCaptured) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Postgres is down")
        took.append((type(captured.exc), captured.context.get("dropped")))

    monkeypatch.setattr(capture, "_trackers", [down_on_its_first_call])

    await capture.CaptureDrain(0).tick()
    await capture.CaptureDrain(0).tick()

    # The tracker's own failure carries the context of the capture it failed on, the report's.
    assert took == [(RuntimeError, 3), (capture.CaptureQueueOverflowed, 3)]


@pytest.mark.asyncio
async def test_a_shortfall_kept_through_an_outage_is_said_once(log_chain, monkeypatch):
    """``capture.overflowed`` is written at ``error``, the level of a bug: said on every tick the
    tracker stays down, one shortfall would read as a new one each second (AGENTS: a failure that
    repeats is one bug). It is said with the report a tracker takes, and with its whole count."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    capture._overflow.dropped = 3
    calls = 0

    async def down_on_its_first_two_calls(_captured: capture.ExceptionCaptured) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [down_on_its_first_two_calls])

    for _ in range(3):
        await capture.CaptureDrain(0).tick()

    said = [
        line.payload["dropped"]
        for line in log_chain()
        if line.logger == capture.__name__ and line.name == "capture.overflowed"
    ]
    assert said == [3]


@pytest.mark.asyncio
async def test_the_dropped_shortfall_is_never_replayed_into_a_tracker_that_already_took_it(
    monkeypatch,
):
    """The overflow report's own retry state persists across ticks, the same ownership a queued
    capture carries: a healthy tracker that already took today's shortfall must not be handed the
    same report again merely because a different tracker is still down."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    capture._overflow.dropped = 3
    capture._overflow.retry = capture._Retry()
    capture._overflow.offered_as = 3
    overflow_reports_seen_by_healthy = 0

    async def healthy(captured: capture.ExceptionCaptured) -> None:
        nonlocal overflow_reports_seen_by_healthy
        if isinstance(captured.exc, capture.CaptureQueueOverflowed):
            overflow_reports_seen_by_healthy += 1

    async def always_down(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [healthy, always_down])

    for _ in range(3):
        await capture.CaptureDrain(0).tick()

    assert overflow_reports_seen_by_healthy == 1


@pytest.mark.asyncio
async def test_a_shortfall_that_grows_while_a_tracker_stays_down_is_not_undercounted(monkeypatch):
    """Persisting the report's ownership so it is not replayed must not freeze a healthy tracker's
    view of the count either: more dropped while a different tracker still owes the earlier
    figure is a bigger fact, offered to everyone again rather than the increment going to
    nobody."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    capture._overflow.dropped = 3
    capture._overflow.retry = capture._Retry()
    capture._overflow.offered_as = 0
    seen_by_healthy: list[int] = []

    async def healthy(captured: capture.ExceptionCaptured) -> None:
        seen_by_healthy.append(captured.context["dropped"])

    async def down_until_it_sees_the_full_count(captured: capture.ExceptionCaptured) -> None:
        if captured.context["dropped"] < 8:
            raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [healthy, down_until_it_sees_the_full_count])

    await capture.CaptureDrain(0).tick()
    capture._overflow.dropped += 5  # more shed while the tracker above stays down
    await capture.CaptureDrain(0).tick()

    assert seen_by_healthy[-1] == 8


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


@pytest.mark.asyncio
async def test_a_capture_stays_queued_until_a_tracker_takes_it(monkeypatch):
    """Postgres going down mid-drain is a tracker raising, not a capture that stops mattering:
    the fingerprinting that would have turned it into an issue never ran, so the outage that
    explains itself has to survive to the tick where a tracker finally takes it — never lost
    with the very failure it would have opened an issue for. The tracker's own failure is queued
    beside it, so once the database is back the outage and the tracker's breakage are two issues.
    """
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    calls = 0
    took: list[str] = []

    async def down_on_its_first_call(captured: capture.ExceptionCaptured) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("Postgres is down")
        took.append(str(captured.exc))

    monkeypatch.setattr(capture, "_trackers", [down_on_its_first_call])
    capture._QUEUE.clear()
    structlog.get_logger(_PROBE_LOGGER).exception("todo.blew_up", exc_info=RuntimeError("outage"))

    await capture.CaptureDrain(0).tick()
    await capture.CaptureDrain(0).tick()

    assert (sorted(took), len(capture._QUEUE)) == (["Postgres is down", "outage"], 0)


@pytest.mark.asyncio
async def test_a_requeued_capture_reports_the_overflow_it_causes(monkeypatch):
    """A tracker's own await is exactly where a concurrent request can log its own failure and
    fill the one free slot: the re-append after a failed tracker meets a full queue like any
    other append, and the eviction that follows has to be counted the same way capture_processor
    counts one, or the overflow figure under-reports what the queue actually shed. The tracker is
    already known broken, so its failure only warns and the one eviction is the requeue's."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=1))
    capture._overflow.dropped = 0
    arrival = capture.ExceptionCaptured(exc=RuntimeError("arrived mid-drain"), context={})

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        capture._QUEUE.append(arrival)  # a concurrent request's own capture, mid-drain
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [flaky])
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary({flaky: 1}))
    outage = capture.ExceptionCaptured(exc=RuntimeError("outage"), context={})
    capture._QUEUE.append(outage)

    await capture.CaptureDrain(0).tick()

    assert capture._overflow.dropped == 1


@pytest.mark.asyncio
async def test_a_requeued_capture_sheds_a_duplicate_rather_than_a_distinct_one(monkeypatch):
    """An outage is when both happen at once: the tracker is down, so its capture comes back, and
    the storm it causes fills the queue meanwhile. The requeue makes room the way any capture
    does, out of the storm's duplicates, never out of the distinct capture queued ahead of it."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=3))
    capture._overflow.dropped = 0
    storm = [capture.ExceptionCaptured(exc=ValueError(f"storm {i}")) for i in range(2)]

    async def down_through_a_storm(_captured: capture.ExceptionCaptured) -> None:
        capture._QUEUE.extend(storm)  # concurrent requests failing the same way, mid-drain
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [down_through_a_storm])
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary({down_through_a_storm: 1}))
    capture._QUEUE.extend(
        [
            capture.ExceptionCaptured(exc=RuntimeError("outage")),
            capture.ExceptionCaptured(exc=KeyError("distinct")),
        ]
    )

    await capture.CaptureDrain(0).tick()

    assert [str(captured.exc) for captured in capture._QUEUE] == ["'distinct'", "storm 1", "outage"]


@pytest.mark.asyncio
async def test_a_stayed_capture_rejoins_the_back_of_the_queue(monkeypatch):
    """The requeue is an ordinary append, not a jump back to the front: a capture whose tracker
    just failed waits behind whatever else is already queued, so a storm of failures still
    drains in the order it arrived instead of the same one spinning at the head forever: the
    tick after a failed one probes the capture that was waiting behind it."""
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
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
    await capture.CaptureDrain(0).tick()

    assert seen == ["first", "second"]


@pytest.mark.asyncio
async def test_a_tracker_that_took_nothing_is_probed_with_one_capture_per_tick(monkeypatch):
    """Kept captures are what an outage leaves behind, a whole queue of them: handing each one to
    a tracker that is down would cost a failing Postgres connection per capture, every second,
    for as long as the outage lasts. The first capture no tracker took ends the tick; the rest
    wait for one that finds the tracker back."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    seen: list[str] = []

    async def always_fails(captured: capture.ExceptionCaptured) -> None:
        seen.append(str(captured.exc))
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [always_fails])
    capture._QUEUE.extend(
        capture.ExceptionCaptured(exc=RuntimeError(name)) for name in ("first", "second", "third")
    )

    await capture.CaptureDrain(0).tick()

    assert seen == ["first"]


# Every deploy ends the process with SIGTERM: what the queue holds then must be delivered.


# A tracker raising ``CancelledError`` (a ``BaseException``) is skipped like any failing tracker.


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", [asyncio.CancelledError, SystemExit], ids=["CancelledError", "SystemExit"]
)
async def test_a_tracker_raising_any_base_exception_does_not_kill_the_drain(
    failure, log_chain, monkeypatch
):
    """``flaky`` staying down means ``first`` is still owed to it after the first tick, so it
    rejoins the queue behind ``second`` rather than being dropped — the second tick is what lets
    ``fine`` see ``second`` too, with the drain still standing after ``flaky``'s exception."""
    tracked: list[capture.ExceptionCaptured] = []

    async def flaky(_captured: capture.ExceptionCaptured) -> None:
        raise failure("tracker bug")

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
    """A broken tracker must reach the queue itself, or it can never become an issue — beside
    the capture it could not take, which stays for the tick that finds it back."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())

    async def failing_tracker(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("tracker itself is down")

    monkeypatch.setattr(capture, "_trackers", [failing_tracker])
    structlog.get_logger(_PROBE_LOGGER).exception(
        "todo.blew_up", exc_info=RuntimeError("the original failure")
    )

    await capture.CaptureDrain(0).tick()

    assert sorted(str(captured.exc) for captured in capture._QUEUE) == [
        "the original failure",
        "tracker itself is down",
    ]


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

    tracker_captures = [
        captured.context
        for captured in capture._QUEUE
        if str(captured.exc) == "tracker itself is down"
    ]
    assert tracker_captures == [
        {
            "event": "todo.blew_up",
            "logger": _PROBE_LOGGER,
            "request_id": "req-1",
            "tracker": repr(failing_tracker),
        }
    ]


# A tracker failing every tick is captured once (AGENTS: a failure that repeats is one bug).
# Through the outage the queue holds the capture no tracker took and the tracker's one failure.


@pytest.mark.asyncio
async def test_a_permanently_broken_tracker_does_not_keep_the_queue_growing(log_chain, monkeypatch):
    """One tick, one probe, one line: the first failure is the issue, every tick after it warns,
    the way :mod:`apps.shared.logs.loop` reports the lifespan workers."""
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

    reported = [
        line.level
        for line in reversed(log_chain())  # oldest first
        if line.logger == capture.__name__ and line.name == "capture.tracker_failed"
    ]
    assert (sorted(str(captured.exc) for captured in capture._QUEUE), reported) == (
        ["the original failure", "tracker itself is down"],
        ["error", "warning", "warning", "warning", "warning"],
    )


@pytest.mark.asyncio
async def test_a_capture_a_healthy_tracker_took_stays_owed_to_the_one_still_down(monkeypatch):
    """Retry is tracked per tracker: the healthy one is asked for each distinct capture exactly
    once, never replayed, while the down one keeps being offered the very capture it still owes,
    until it takes it."""
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    seen_by_healthy: list[str] = []
    down_calls = 0

    async def healthy(captured: capture.ExceptionCaptured) -> None:
        seen_by_healthy.append(str(captured.exc))

    async def down_for_its_first_call(_captured: capture.ExceptionCaptured) -> None:
        nonlocal down_calls
        down_calls += 1
        if down_calls == 1:
            raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [healthy, down_for_its_first_call])
    capture._QUEUE.clear()
    capture._QUEUE.append(capture.ExceptionCaptured(exc=RuntimeError("outage")))

    await capture.CaptureDrain(0).tick()
    await capture.CaptureDrain(0).tick()

    # "outage" fails down_for_its_first_call's first call and is offered to it again once the
    # tracker's own failure capture has cleared; that second offer is the one a bool verdict
    # would have skipped by reading "outage" as already done.
    assert (seen_by_healthy, down_calls, list(capture._QUEUE)) == (
        ["outage", "Postgres is down"],
        3,
        [],
    )


@pytest.mark.asyncio
async def test_a_down_tracker_throttles_every_tracker_to_one_capture_per_tick(monkeypatch):
    """Ending the tick on the first capture still owed to someone protects the down tracker from a
    second failing call the same tick — the price, with more than one tracker registered, is that
    a healthy tracker also waits a tick per capture rather than draining the queue at once. Only
    one tracker is registered today (``apps/issues``), which never pays it."""
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    seen_by_healthy: list[str] = []

    async def healthy(captured: capture.ExceptionCaptured) -> None:
        seen_by_healthy.append(str(captured.exc))

    async def always_down(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [healthy, always_down])
    capture._QUEUE.clear()
    capture._QUEUE.extend(
        capture.ExceptionCaptured(exc=RuntimeError(name)) for name in ("first", "second", "third")
    )

    await capture.CaptureDrain(0).tick()

    assert seen_by_healthy == ["first"]


@pytest.mark.asyncio
async def test_a_capture_no_tracker_can_ever_take_is_parked_past_its_retry_window(
    log_chain, monkeypatch
):
    """A capture whose tracker fails for a reason that never clears — a value Postgres' JSON type
    rejects, reachable through ``_track``'s ``json.dumps`` — is parked past a bounded retry
    window, the way ``TaskWorker`` parks a task that keeps failing, with one line marking the
    drop rather than a fresh traceback forever. The window is real elapsed time, not a tick
    count: an ordinary outage must survive it, so the clock — not the tick loop — is what the
    budget is spent against."""
    monkeypatch.setattr(get_technical_settings(), "capture_retry_seconds", 120, raising=False)
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: moment)

    async def never_takes_it(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("Postgres' JSON type rejects this capture's context")

    monkeypatch.setattr(capture, "_trackers", [never_takes_it])
    capture._QUEUE.append(capture.ExceptionCaptured(exc=RuntimeError("unstorable")))

    await capture.CaptureDrain(0).tick()  # t=0: opens the window for "unstorable"
    moment += timedelta(seconds=60)
    await capture.CaptureDrain(0).tick()  # t=60: still inside the window
    moment += timedelta(seconds=61)
    await capture.CaptureDrain(0).tick()  # t=121: past it -> "unstorable" is parked
    moment += timedelta(seconds=61)
    await capture.CaptureDrain(0).tick()  # t=182: the tracker's own failure parks too

    parked = [
        line.payload["attempts"]
        for line in reversed(log_chain())  # oldest first
        if line.logger == capture.__name__ and line.name == "capture.parked"
    ]
    assert (list(capture._QUEUE), parked) == ([], [2, 2])


@pytest.mark.asyncio
async def test_parking_is_never_a_count_of_tries_short_of_the_retry_window(monkeypatch):
    """The budget is real elapsed time, never a count of tries: many fast ticks while the clock
    barely moves must not burn through it the way an attempt-count ceiling would — only elapsed
    time past the window parks a capture."""
    monkeypatch.setattr(get_technical_settings(), "capture_retry_seconds", 120, raising=False)
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: moment)

    async def always_down(_captured: capture.ExceptionCaptured) -> None:
        raise RuntimeError("Postgres is down")

    monkeypatch.setattr(capture, "_trackers", [always_down])
    capture._QUEUE.append(capture.ExceptionCaptured(exc=RuntimeError("outage")))

    for _ in range(10):
        await capture.CaptureDrain(0).tick()
        moment += timedelta(seconds=1)

    assert sorted(str(c.exc) for c in capture._QUEUE) == ["Postgres is down", "outage"]


@pytest.mark.asyncio
async def test_a_capture_outlives_an_ordinary_outage_inside_its_retry_window(monkeypatch):
    """The retry window bounds a capture nothing can ever store, not an outage that will end: a
    tracker down for a while and then back must still take the capture it owed, never parked
    merely for having waited."""
    monkeypatch.setattr(get_technical_settings(), "capture_retry_seconds", 120, raising=False)
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=10))
    monkeypatch.setattr(capture, "_tracker_failures", WeakKeyDictionary())
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    monkeypatch.setattr(clock, "now", lambda: moment)
    taken: list[str] = []

    async def recovers_at_two_minutes(captured: capture.ExceptionCaptured) -> None:
        if moment < datetime(2026, 1, 1, 0, 2, tzinfo=UTC):
            raise RuntimeError("Postgres is down")
        taken.append(str(captured.exc))

    monkeypatch.setattr(capture, "_trackers", [recovers_at_two_minutes])
    capture._QUEUE.append(capture.ExceptionCaptured(exc=RuntimeError("outage")))

    for _ in range(3):
        await capture.CaptureDrain(0).tick()
        moment += timedelta(seconds=60)

    assert (sorted(taken), list(capture._QUEUE)) == (["Postgres is down", "outage"], [])


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
