"""A background task is one thing to the host, not two hooks to remember.

Every context that runs one used to register ``on_startup(x.start)`` and
``on_shutdown(x.stop)`` by hand — five sites, where forgetting the second half leaves a task
that never stops and nothing to notice it.
"""

from dataclasses import dataclass, field

from fastapi.testclient import TestClient

from apps.shared.host import Host


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
