"""One invariant over the *lifespan loops*: a loop that falls over is not a warning.

The five background workers all wrap their tick in ``except Exception`` — they have to, since one
bad tick must never end the loop. What that bought was silence: a task worker that stopped
claiming, or an event listener that stopped delivering, left nothing but a ``warning`` inside a
log window that rolls over in two days, so the console showed a healthy server while the
durable half of the event system was dead.

Three of the five now put that failure through the verdict in
``apps.shared.logs.loop`` — the transition into failure is a bug, the ticks after it are
the same outage, the recovery carries the toll. The other two are excluded *on purpose* and stay
at ``warning``: the log writer and the capture drain are the machinery the seam itself runs
on, so an ``exception`` from either would re-enter the queue it just failed to drain.

This lives at the root rather than in ``apps/shared/tests`` for the reason
``test_event_vocabulary`` does: shared may not import a bounded context, and one of the three
loops is ``apps.metrics``'.
"""

import pytest
from structlog.testing import capture_logs

from apps.metrics.infra.flusher import MetricsFlusher
from apps.shared.events.listener import EventListener
from apps.shared.queue import TaskWorker

# ``(the loop's name, how to build one)`` — the name is what the verdict derives both of its
# event names from, so asserting it is asserting that each loop kept the line it always wrote.
# A factory rather than an instance: the health state *is* "has this loop been failing", so a
# worker shared between two tests would carry the first one's outage into the second.
_LOOPS = [
    ("queue.worker", lambda: TaskWorker(interval_seconds=0)),
    ("listener.tick", lambda: EventListener(interval_seconds=0)),
    ("metrics.flush", lambda: MetricsFlusher(interval_seconds=0)),
]


@pytest.mark.parametrize(("name", "build"), _LOOPS, ids=[name for name, _ in _LOOPS])
@pytest.mark.asyncio
async def test_a_lifespan_loop_that_falls_over_opens_an_issue(name, build, monkeypatch):
    """``error`` carrying a live exception *is* the capture seam — the one level that reaches the
    console. A worker nobody is retrying has no other way to be seen."""

    async def broken(*_args, **_kwargs):
        raise RuntimeError("the loop's own query blew up")

    worker = build()
    monkeypatch.setattr(worker, "tick", broken)

    with capture_logs() as logs:
        await worker.guarded_tick()

    assert [(entry["event"], entry["log_level"]) for entry in logs] == [(f"{name}_failed", "error")]


@pytest.mark.parametrize(("name", "build"), _LOOPS, ids=[name for name, _ in _LOOPS])
@pytest.mark.asyncio
async def test_a_healthy_lifespan_loop_writes_nothing(name, build, monkeypatch):
    """A line per successful tick is a line per second, per worker, forever."""

    async def fine(*_args, **_kwargs):
        return 0

    worker = build()
    monkeypatch.setattr(worker, "tick", fine)

    with capture_logs() as logs:
        await worker.guarded_tick()

    assert logs == []
