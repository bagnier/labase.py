"""The log sink: the runtime log path enqueues, the background drain writes to the store.

Proves the non-blocking doctrine — the structlog processor touches neither disk nor database, only
the queue grows — and the fallback that makes moving the log stream into Postgres safe: when the
store is the thing that is down, the batch still lands in its day file, and the outage is
announced once rather than once per line.
"""

import json
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.logs import sink
from apps.shared.logs.repository import LogRepository
from apps.shared.logs.sink import (
    LogDrain,
    clear_log_sink,
    enqueue_line,
    fallback_dir,
    log_processor,
)
from apps.shared.persistence import database as db

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_sink(tmp_path, monkeypatch):
    """A scratch fallback dir and an empty queue, so one test's lines never bleed into another's."""
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(sink, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
    clear_log_sink()
    yield
    clear_log_sink()


@pytest_asyncio.fixture
async def store():
    """A reader on the store, with the engine-cache hygiene a driver-based neighbour would break."""
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    async with db.admin_session_factory()() as session:
        yield session
    await db._admin_engine().dispose()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


def _enqueue(event: str) -> None:
    enqueue_line({"event": event, "timestamp": _NOW.isoformat(), "level": "info"})


def test_processor_enqueues_without_writing():
    """The critical-path guarantee: the processor only appends to the queue."""
    log_processor(None, "info", {"event": "todo.created", "timestamp": _NOW.isoformat()})

    assert (len(sink._QUEUE), list(fallback_dir().glob("firehose-*.jsonl"))) == (1, [])


def test_processor_snapshots_the_event_dict():
    """A snapshot is queued, so a later processor mutating the live mapping cannot corrupt it."""
    live = {"event": "e", "timestamp": _NOW.isoformat()}

    log_processor(None, "info", live)
    live["event"] = "mutated"  # a downstream processor rewrites the shared dict

    assert sink._QUEUE[0]["event"] == "e"


@pytest.mark.asyncio
async def test_a_tick_drains_the_queue_into_the_store(store):
    marker = f"drain.{uuid.uuid4().hex}"
    _enqueue(marker)

    await LogDrain(interval_seconds=0).tick()

    found = [line.name for line in await LogRepository(store).search(text=marker)]
    assert (list(sink._QUEUE), found) == ([], [marker])


@pytest.mark.asyncio
async def test_stop_drains_what_the_loop_left_behind(store):
    """SIGTERM is how every deploy ends a process: what the writer is holding at that moment is
    the normal amount to lose, not an edge case."""
    marker = f"tail.{uuid.uuid4().hex}"
    writer = LogDrain(interval_seconds=0)
    _enqueue(marker)

    await writer.stop()  # never started, but stop must still drain

    assert [line.name for line in await LogRepository(store).search(text=marker)] == [marker]


# The queue is bounded, so under a burst it sheds — and a shed line is one the Timeline will never
# show. Silence there reads exactly like a quiet server, which is the failure mode the whole sink
# exists to avoid; the capture queue has said its shortfall since the day it was written.


@pytest.mark.asyncio
async def test_the_drain_reports_the_lines_the_queue_had_to_shed(log_chain, store, monkeypatch):
    """Dropping the oldest in silence loses the very lines a reader is looking for, and the count
    has to come from the drain: it is the only side of the sink that still has a voice once the
    queue is full."""
    monkeypatch.setattr(sink, "_QUEUE", deque(maxlen=2))

    for i in range(5):
        _enqueue(f"shed.{i}")
    await LogDrain(interval_seconds=0).tick()

    assert [
        (line.name, line.payload.get("dropped"))
        for line in log_chain()
        if line.name == "log_sink.overflowed"
    ] == [("log_sink.overflowed", 3)]


# The store can refuse — Postgres down, a pool exhausted, a migration mid-flight. Swallowed, that
# turns the log sink off in silence: the Timeline simply shows nothing, which reads as a quiet
# server. So the batch goes to the day file instead, and the outage is said once.


@contextmanager
def _a_store_that_refuses():
    """Take the database away from the drain, the way an outage does — and give it back on exit.

    Saved and restored by hand rather than with ``monkeypatch``: monkeypatch undoes at the end of
    the *test*, not at the end of the ``with``, so the recovery half of an outage would never
    happen.
    """

    def refuse():
        raise ConnectionError("the store is gone")

    real = sink.admin_session_factory
    sink.admin_session_factory = refuse
    try:
        yield
    finally:
        sink.admin_session_factory = real


@pytest.mark.asyncio
async def test_a_batch_the_store_refuses_lands_in_the_day_file():
    """A database outage is precisely when an operator still wants to read the log."""
    with _a_store_that_refuses():
        _enqueue("lost.line")
        await LogDrain(interval_seconds=0).tick()

    written = [
        json.loads(raw)
        for path in fallback_dir().glob("firehose-*.jsonl")
        for raw in path.read_text(encoding="utf-8").splitlines()
    ]
    assert [one["event"] for one in written] == ["lost.line"]


@pytest.mark.asyncio
async def test_a_store_that_refuses_is_announced_once(log_chain, caplog):
    """Once per outage, not per refused line: the announcement is itself a log line, so one per
    failed write would feed the very queue that cannot be drained.

    Read off the stream rather than the store, on purpose — the announcement cannot survive its
    own outage, which is why it is also written to stdout, where an aggregator sees it while it is
    happening.
    """
    writer = LogDrain(interval_seconds=0)
    with _a_store_that_refuses():
        for _ in range(3):
            _enqueue("lost.line")
            await writer.tick()

    announced = [r for r in caplog.records if r.msg.get("event") == "log_sink.write_failed"]
    assert len(announced) == 1


@pytest.mark.asyncio
async def test_a_store_that_comes_back_says_what_the_outage_cost(log_chain, store):
    """The recovery line is the only one that can carry the toll: during the outage the count is
    still climbing, and nothing written then reaches the store to be read back.

    Three, for two lost lines: the ``write_failed`` announcement is itself a log line, and it was
    written while the store was refusing — so it was refused too, and counting it is the truth.
    """
    writer = LogDrain(interval_seconds=0)
    with _a_store_that_refuses():
        for _ in range(2):
            _enqueue("lost.line")
            await writer.tick()

    _enqueue("kept.line")
    await writer.tick()

    assert [
        (line.name, line.payload.get("lines"))
        for line in log_chain()
        if line.name == "log_sink.write_recovered"
    ] == [("log_sink.write_recovered", 3)]
