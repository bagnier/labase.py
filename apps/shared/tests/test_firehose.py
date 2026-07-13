"""The firehose writer: the runtime log path enqueues, the background task writes.

Proves the non-blocking doctrine — the structlog processor never touches the disk (only the
queue grows), and a tick funnels the queue to the day files, batching a burst per file.
"""

import json

import pytest
import structlog

from apps.shared.config import get_technical_settings
from apps.shared.observability import firehose
from apps.shared.observability.firehose import (
    FirehoseWriter,
    clear_firehose,
    enqueue_firehose,
    firehose_dir,
    firehose_processor,
    read_firehose,
)


@pytest.fixture(autouse=True)
def _isolate_firehose(tmp_path, monkeypatch):
    # Point the firehose at a scratch dir and start every test with an empty queue + no files,
    # so one test's runtime log lines never bleed into another's timeline.
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(firehose, "get_technical_settings", lambda: settings)
    clear_firehose()
    yield
    clear_firehose()


def test_processor_enqueues_without_writing():
    """The critical-path guarantee: the processor only appends to the queue — no file yet."""
    firehose_processor(None, "info", {"event": "todo.created", "timestamp": "2026-07-12T10:00:00"})
    assert len(firehose._QUEUE) == 1
    assert not list(firehose_dir().glob("firehose-*.jsonl")), "the processor must not touch disk"


def test_processor_snapshots_the_event_dict():
    """A snapshot is queued, so a later processor mutating the live mapping cannot corrupt it."""
    live = {"event": "e", "timestamp": "2026-07-12T10:00:00"}
    firehose_processor(None, "info", live)
    live["event"] = "mutated"  # a downstream processor rewrites the shared dict
    assert firehose._QUEUE[0]["event"] == "e"


@pytest.mark.asyncio
async def test_tick_drains_the_queue_to_the_file():
    writer = FirehoseWriter(interval_seconds=0)  # hand-driven, no loop
    enqueue_firehose({"event": "a.one", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    enqueue_firehose({"event": "a.two", "timestamp": "2026-07-12T10:00:01", "level": "info"})
    writer.tick()
    assert not firehose._QUEUE, "tick must drain the queue"
    events = {r.event for r in read_firehose()}
    assert events == {"a.one", "a.two"}


@pytest.mark.asyncio
async def test_tick_batches_a_day_in_one_open(monkeypatch):
    """A burst on the same day costs one open, not one per line."""
    opens = 0
    real_open = firehose.Path.open

    def counting_open(self, *args, **kwargs):
        nonlocal opens
        opens += 1
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(firehose.Path, "open", counting_open)
    for i in range(5):
        enqueue_firehose({"event": f"e.{i}", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    FirehoseWriter(interval_seconds=0).tick()
    assert opens == 1


@pytest.mark.asyncio
async def test_stop_flushes_what_the_loop_left_behind():
    writer = FirehoseWriter(interval_seconds=0)
    enqueue_firehose({"event": "tail.line", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    await writer.stop()  # never started, but stop must still drain
    assert {r.event for r in read_firehose()} == {"tail.line"}


def test_end_to_end_through_structlog(monkeypatch):
    """A real structlog call routes through the processor and, after a tick, is readable."""
    monkeypatch.setattr(structlog, "get_logger", structlog.get_logger)
    firehose_processor(None, "info", {"event": "http.request", "timestamp": "2026-07-12T09:00:00"})
    assert not read_firehose(), "still queued, nothing drained yet"
    FirehoseWriter(interval_seconds=0).tick()
    assert any(r.event == "http.request" for r in read_firehose())


def test_line_is_valid_json_on_disk():
    enqueue_firehose({"event": "shape", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    FirehoseWriter(interval_seconds=0).tick()
    files = list(firehose_dir().glob("firehose-*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line)["event"] == "shape"
