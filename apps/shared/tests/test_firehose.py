"""The firehose writer: the runtime log path enqueues, the background task writes.

Proves the non-blocking doctrine — the structlog processor never touches the disk (only the
queue grows), and a tick funnels the queue to the day files, batching a burst per file.
"""

import asyncio
import json
import threading
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
import structlog

from apps.shared import clock
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

# The fixed day every test's log lines are stamped with. read_firehose() reads only the recent
# window (now - FIREHOSE_WINDOW), so the clock is pinned here to keep that window deterministic
# regardless of the real date (otherwise these rows fall out of the window a few days on).
_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_firehose(tmp_path, monkeypatch):
    # Point the firehose at a scratch dir and start every test with an empty queue + no files,
    # so one test's runtime log lines never bleed into another's timeline.
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(firehose, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
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
    events = {r.name for r in read_firehose()}
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
    assert {r.name for r in read_firehose()} == {"tail.line"}


def test_end_to_end_through_structlog(monkeypatch):
    """A real structlog call routes through the processor and, after a tick, is readable."""
    monkeypatch.setattr(structlog, "get_logger", structlog.get_logger)
    firehose_processor(None, "info", {"event": "http.request", "timestamp": "2026-07-12T09:00:00"})
    assert not read_firehose(), "still queued, nothing drained yet"
    FirehoseWriter(interval_seconds=0).tick()
    assert any(r.name == "http.request" for r in read_firehose())


def test_line_is_valid_json_on_disk():
    enqueue_firehose({"event": "shape", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    FirehoseWriter(interval_seconds=0).tick()
    files = list(firehose_dir().glob("firehose-*.jsonl"))
    assert len(files) == 1
    line = files[0].read_text(encoding="utf-8").splitlines()[0]
    assert json.loads(line)["event"] == "shape"


@pytest.mark.asyncio
async def test_the_periodic_drain_writes_off_the_event_loop(monkeypatch):
    """The batch write is blocking disk I/O. Done on the loop it stalls every request in
    flight — once per interval, and for as long as a burst of queued lines takes."""
    on_loop_thread: list[bool] = []
    real_open = firehose.Path.open

    def recording_open(self, *args, **kwargs):
        on_loop_thread.append(threading.current_thread() is threading.main_thread())
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(firehose.Path, "open", recording_open)
    enqueue_firehose({"event": "a.line", "timestamp": "2026-07-12T10:00:00", "level": "info"})
    writer = FirehoseWriter(interval_seconds=0.01)
    await writer.start()
    async with asyncio.timeout(2):  # the loop keeps turning only if the write is elsewhere
        while not on_loop_thread:
            await asyncio.sleep(0.005)
    await writer.stop()

    assert on_loop_thread == [False]


# The disk can refuse — a full volume, a read-only mount, a directory that vanished under a
# rotation. Swallowed, that turns the firehose off in silence: the timeline simply shows nothing,
# and reads as a quiet server. The writer says it instead, once per outage rather than per line.


@contextmanager
def _a_disk_that_refuses():
    """Put a *directory* where the day's file belongs, so every ``open(..., "a")`` on it raises
    ``IsADirectoryError``.

    A full volume or a read-only mount does the same thing to the writer, and this is the version
    a test can set up and take down on demand — the real ``_write_batch`` runs throughout, which a
    patched one would not.
    """
    blocked = firehose._file_for(_NOW)
    blocked.mkdir()
    try:
        yield
    finally:
        blocked.rmdir()  # before any read: the reader globs this name and would try to parse it


def _write(event: str, writer: FirehoseWriter) -> None:
    enqueue_firehose({"timestamp": _NOW.isoformat(), "event": event})
    writer.tick()


def test_a_disk_that_refuses_the_write_is_announced_once(log_chain, caplog):
    """Once per outage, not per refused line: the announcement is itself a log line, so one per
    failed write would feed the very queue that cannot be drained.

    Read off the stream rather than the file on purpose — the announcement cannot survive its own
    outage on disk, which is exactly why it is also written to stdout, where an aggregator sees it
    while it is happening.
    """
    writer = FirehoseWriter(interval_seconds=0)
    with _a_disk_that_refuses():
        for _ in range(3):
            _write("lost.line", writer)

    announced = [r for r in caplog.records if r.msg.get("event") == "firehose.write_failed"]
    assert len(announced) == 1


def test_a_disk_that_comes_back_says_what_it_cost(log_chain):
    """The recovery line is the only one that can carry the toll: during the outage the count is
    still climbing, and nothing written then reaches the file to be read back."""
    writer = FirehoseWriter(interval_seconds=0)
    with _a_disk_that_refuses():
        _write("lost.line", writer)
        _write("lost.line", writer)

    _write("kept.line", writer)

    # Two, not three: the announcement is stamped by structlog's own clock, so it belongs to
    # today's file rather than the pinned day this test blocked — it is not part of the toll.
    assert [
        (line.name, line.payload.get("lines"))
        for line in log_chain()
        if line.name == "firehose.write_recovered"
    ] == [("firehose.write_recovered", 2)]
