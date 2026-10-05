"""The log sink: the processor only enqueues, the drain writes to the store, and a refused batch
lands in its day file with the outage said once."""

import asyncio
import json
import threading
import uuid
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text

from apps.shared import clock
from apps.shared.logs import sink
from apps.shared.logs.chain import apply_log_level
from apps.shared.logs.repository import LogRepository
from apps.shared.logs.sink import (
    LogDrain,
    clear_log_sink,
    enqueue_line,
    fallback_dir,
    log_processor,
)
from apps.shared.persistence import database as db
from apps.shared.settings.env import get_technical_settings

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_sink(tmp_path, monkeypatch):
    settings = get_technical_settings()
    monkeypatch.setattr(settings, "firehose_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(sink, "get_technical_settings", lambda: settings)
    monkeypatch.setattr(clock, "now", lambda: _NOW)
    clear_log_sink()
    yield
    clear_log_sink()


@pytest_asyncio.fixture
async def store():
    """A reader on the store, with fresh engine caches."""
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
    log_processor(None, "info", {"event": "todo.created", "timestamp": _NOW.isoformat()})

    assert (len(sink._QUEUE), list(fallback_dir().glob("firehose-*.jsonl"))) == (1, [])


def test_processor_snapshots_the_event_dict():
    live = {"event": "e", "timestamp": _NOW.isoformat()}

    log_processor(None, "info", live)
    live["event"] = "mutated"

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
    marker = f"tail.{uuid.uuid4().hex}"
    writer = LogDrain(interval_seconds=0)
    _enqueue(marker)

    await writer.stop()  # never started

    assert [line.name for line in await LogRepository(store).search(text=marker)] == [marker]


# Under a burst the bounded queue drops lines; silence would read like a quiet server.


@pytest.mark.asyncio
async def test_the_drain_reports_the_lines_the_queue_had_to_shed(log_chain, store, monkeypatch):
    """Reported by the drain: a line from the full queue's side would only feed it."""
    monkeypatch.setattr(sink, "_QUEUE", deque(maxlen=2))

    for i in range(5):
        _enqueue(f"shed.{i}")
    await LogDrain(interval_seconds=0).tick()

    assert [
        (line.name, line.payload.get("dropped"))
        for line in log_chain()
        if line.name == "log_sink.overflowed"
    ] == [("log_sink.overflowed", 3)]


# When the store refuses (Postgres down, pool exhausted), the batch goes to the day file and the
# outage is said once.


@contextmanager
def _a_store_that_refuses():
    """An outage for the drain, lifted on exit. Not ``monkeypatch``, which undoes only at the end
    of the test: the recovery would never happen."""

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
async def test_a_lock_the_drain_cannot_get_falls_back_like_a_refusal(monkeypatch, store):
    """The e2e driver's TRUNCATE (tests/e2e/cleanup.py) holds the table: the drain gives up after
    its own timeout, pinned small here; the outer guard fails the test if nothing bounds it."""
    monkeypatch.setattr(get_technical_settings(), "log_drain_lock_timeout_seconds", 0.05)
    _enqueue("locked.line")
    await store.execute(text("LOCK TABLE log_lines IN ACCESS EXCLUSIVE MODE"))

    async with asyncio.timeout(5):
        await LogDrain(interval_seconds=0).tick()

    written = [
        json.loads(raw)["event"]
        for path in fallback_dir().glob("firehose-*.jsonl")
        for raw in path.read_text(encoding="utf-8").splitlines()
    ]
    assert written == ["locked.line"]


@pytest.mark.asyncio
async def test_a_refused_batch_is_written_while_the_loop_keeps_serving(monkeypatch):
    """The day-file write is off the event loop. The double holds the write until the loop,
    still serving, releases it; written on the loop, it would wait out its bound."""
    released = threading.Event()
    releases_seen: list[bool] = []
    monkeypatch.setattr(
        sink, "_write_to_files", lambda lines: releases_seen.append(released.wait(timeout=1))
    )
    _enqueue("lost.line")

    with _a_store_that_refuses():
        tick = asyncio.ensure_future(LogDrain(interval_seconds=0).tick())
        await asyncio.sleep(0)
        released.set()
        await tick

    assert releases_seen == [True]


@pytest.mark.asyncio
async def test_a_store_that_refuses_is_announced_once(log_chain, caplog):
    """Read off stdout: during the outage, the store cannot hold it."""
    writer = LogDrain(interval_seconds=0)
    with _a_store_that_refuses():
        for _ in range(3):
            _enqueue("lost.line")
            await writer.tick()

    announced = [r for r in caplog.records if r.msg.get("event") == "log_sink.write_failed"]
    assert len(announced) == 1


@pytest.mark.asyncio
async def test_a_store_that_comes_back_says_what_the_outage_cost(log_chain, store):
    """Three for two lost lines: the ``write_failed`` announcement was refused too."""
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


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["INFO", "WARNING", "ERROR"])
async def test_outage_and_recovery_are_said_at_every_log_level(log_chain, caplog, store, level):
    """``timeline.log_level`` never quiets them."""
    apply_log_level(level)
    writer = LogDrain(interval_seconds=0)
    with _a_store_that_refuses():
        _enqueue("lost.line")
        await writer.tick()
    _enqueue("kept.line")
    await writer.tick()

    transitions = sorted(
        r.msg.get("event")
        for r in caplog.records
        if r.msg.get("event", "").startswith("log_sink.write_")
    )
    # Enqueued after the write it reports, the recovery line is still queued: proof it went
    # through ``log_processor``, not only to the console.
    queued = [line.name for line in log_chain()]
    assert (transitions, queued) == (
        ["log_sink.write_failed", "log_sink.write_recovered"],
        ["log_sink.write_recovered"],
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("level", ["INFO", "WARNING", "ERROR"])
async def test_overflow_is_said_at_every_log_level(log_chain, store, monkeypatch, level):
    """``timeline.log_level`` never quiets it."""
    monkeypatch.setattr(sink, "_QUEUE", deque(maxlen=2))
    apply_log_level(level)

    for i in range(5):
        _enqueue(f"shed.{i}")
    await LogDrain(interval_seconds=0).tick()

    assert [
        (line.name, line.payload.get("dropped"))
        for line in log_chain()
        if line.name == "log_sink.overflowed"
    ] == [("log_sink.overflowed", 3)]
