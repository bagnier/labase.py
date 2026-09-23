"""The seam's own edges — what it sheds, what it refuses to count twice, what it still owes.

``apps/issues/tests/test_capture.py`` covers the round trip all the way to the issues tables.
These hold what that round trip cannot state, all four about the *count* an issue carries:

- the queue is bounded so a storm can never eat memory, which means it drops — but it sheds by
  fingerprint, so a storm's own duplicates pay for the room, never a distinct capture behind them;
- the shortfall itself becomes a capture of its own, so it folds into an issue instead of ageing
  out of the log window as a warning nobody tracks;
- one exception is one occurrence however many loggers see it on its way out;
- and the ones still queued when the process is asked to stop are folded in, not dropped.
"""

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


def test_a_storm_of_duplicates_never_evicts_the_distinct_capture_behind_it(monkeypatch):
    """A blind FIFO eviction costs whatever sits at the front of the queue, storm or not — a
    cheap 500 repeated a thousand times would then evict the one distinct failure that arrived
    first. Shedding by fingerprint instead means the storm pays for its own room."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    log = structlog.get_logger(_PROBE_LOGGER)
    try:
        raise KeyError("distinct")
    except KeyError:
        log.exception("todo.blew_up")

    _log_exceptions(5)

    assert [type(captured.exc) for captured in capture._QUEUE] == [KeyError, ValueError]


@pytest.mark.asyncio
async def test_the_drain_reports_the_captures_the_queue_had_to_shed(log_chain, monkeypatch):
    """Silently dropping captures would lose the very exceptions the tracker exists to show,
    and the shortfall has to be said by the drain: the processor runs inside the logging chain,
    where a line of its own would re-enter capture."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [])  # the seam, not what issues does with it
    capture._overflow.dropped = 0

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    [reported] = [line for line in log_chain() if line.logger == capture.__name__]
    assert (reported.name, reported.payload["dropped"]) == ("capture.overflowed", 3)


@pytest.mark.asyncio
async def test_the_dropped_shortfall_becomes_its_own_trackable_capture(monkeypatch):
    """A warning that ages out of the two-day log window leaves nothing an admin can find
    tomorrow (AGENTS: A line says what no other record says) — the shortfall must instead be
    something the seam itself can fold into an issue, the same way it folds any other bug."""
    monkeypatch.setattr(capture, "_QUEUE", deque(maxlen=2))
    monkeypatch.setattr(capture, "_trackers", [])
    capture._overflow.dropped = 0

    _log_exceptions(5)
    await capture.CaptureDrain(0).tick()

    queued = [(type(c.exc), c.context.get("dropped")) for c in capture._QUEUE]
    assert queued == [(capture.CaptureQueueOverflowed, 3)]


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


# Shutdown is not a special case: SIGTERM is how every deploy ends a process, so whatever sits in
# the queue at that moment is the *normal* amount to lose, not an edge one. The log drain
# already emptied on its way out; this one dropped the exceptions it was holding.


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
