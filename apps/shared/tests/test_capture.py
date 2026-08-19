"""The bound on the capture queue — what it sheds, and how a reader learns of it.

``apps/issues/tests/test_capture.py`` covers the round trip all the way to the issues tables.
This holds the one rule that round trip cannot state: the queue is bounded so a storm can never
eat memory, which means it drops — and a dropped capture is an issue nobody will ever see.
"""

from collections import deque

import pytest
import structlog

from apps.shared.observability import capture
from apps.shared.observability.capture import CaptureDrain

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
    await CaptureDrain(0).tick()

    reported = [
        (line.name, line.payload) for line in log_chain() if line.logger == capture.__name__
    ]
    assert reported == [("capture.overflowed", {"dropped": 3})]
