"""``Host.run_background`` and failing startup hooks, which still open an issue."""

from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

from apps.shared.integration.host import Host
from apps.shared.logs import capture


@dataclass
class _RecordingTask:
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


@pytest.fixture
def tracked(monkeypatch) -> Iterator[list[capture.ExceptionCaptured]]:
    """What a tracker was handed. The list is replaced, not appended to: the real tracker would
    bind the cached admin engine to this short-lived loop and break a later test."""
    seen: list[capture.ExceptionCaptured] = []

    async def track(captured: capture.ExceptionCaptured) -> None:
        seen.append(captured)

    monkeypatch.setattr(capture, "_trackers", [track])
    # An empty queue, so a neighbour's capture is not mistaken for this startup's.
    capture._QUEUE.clear()
    yield seen
    capture._QUEUE.clear()


def test_a_startup_that_raises_becomes_an_issue_before_the_process_dies(tracked):
    host = Host()

    async def broken() -> None:
        raise RuntimeError("the pool never came up")

    host.on_startup(broken)

    with pytest.raises(RuntimeError, match="the pool never came up"), TestClient(host.app):
        pass

    assert [str(one.exc) for one in tracked] == ["the pool never came up"]
