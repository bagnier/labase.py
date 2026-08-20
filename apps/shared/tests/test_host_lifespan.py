"""A background task is one thing to the host, not two hooks to remember.

Every context that runs one used to register ``on_startup(x.start)`` and
``on_shutdown(x.stop)`` by hand — five sites, where forgetting the second half leaves a task
that never stops and nothing to notice it.

And a startup that raises is the one failure the capture seam could not deliver: the exception
reaches the chain, but the drain that folds it into an issue is itself a startup hook that never
ran, so the queue died with the process.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from apps.shared.integration.host import Host
from apps.shared.logs import capture


@dataclass
class _RecordingTask:
    """A fake of the lifespan-task shape, recording what the host asked of it."""

    calls: list[str] = field(default_factory=list)

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self) -> None:
        self.calls.append("stop")


def test_a_background_task_is_started_and_stopped_by_the_lifespan():
    host = Host()
    task = _RecordingTask()
    host.run_background(task)

    with TestClient(host.app):
        pass

    assert task.calls == ["start", "stop"]


# The interpreter dying on its own leaves a line and no issue, on purpose (see
# ``logs.chain``): there is no loop left to reach a database on. A failing *startup* is
# the opposite case — the loop is up, the trackers subscribed at mount — and it was going the same
# silent way.


@pytest.fixture
def tracked(monkeypatch) -> Iterator[list[capture.ExceptionCaptured]]:
    """What a tracker would have been handed — the seam, not what issues does with it.

    The tracker list is *replaced*, never appended to: ``apps.main`` is imported by the e2e
    plugin, so the real tracker is subscribed and would open a database session on this test's
    short-lived loop, leaving the cached admin engine bound to a loop that is about to close.
    The next test to reach that engine then dies on "attached to a different loop", three files
    away from the cause — the same trap ``test_capture`` names.
    """
    seen: list[capture.ExceptionCaptured] = []

    async def track(captured: capture.ExceptionCaptured) -> None:
        seen.append(captured)

    monkeypatch.setattr(capture, "_trackers", [track])
    # And an empty queue: the drain takes whatever is in it, so a neighbour's fabricated
    # ``log.exception`` would be handed to this test's tracker as if the startup had raised it.
    capture._QUEUE.clear()
    yield seen
    capture._QUEUE.clear()


def test_a_startup_that_raises_becomes_an_issue_before_the_process_dies(tracked):
    """The boot still fails — that is not negotiable. It just stops failing in silence."""
    host = Host()

    async def broken() -> None:
        raise RuntimeError("the pool never came up")

    host.on_startup(broken)

    with pytest.raises(RuntimeError, match="the pool never came up"), TestClient(host.app):
        pass

    assert [str(one.exc) for one in tracked] == ["the pool never came up"]
