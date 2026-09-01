"""``log_lines`` as a store the whole deployment shares, rather than a file each process keeps.

Per-day JSON lines on local disk made the timeline lie by omission the moment a second instance
existed: the journal and the issues are in Postgres and therefore global, while the ``logs``
source showed only whatever the instance answering that page happened to have written. An admin
correlating a request could see the fact and the occurrence and miss every line between them.

Retention had the same shape of problem from the other end — the module promised that per-day
rotation made it "a plain file delete", and nothing ever deleted.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import text as sql_text

from apps.shared import clock
from apps.shared.logs.repository import LogRepository
from apps.shared.persistence import database as db

_NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _line(event: str, *, ts: datetime = _NOW, **fields) -> dict:
    return {"timestamp": ts.isoformat(), "level": "info", "event": event, **fields}


@pytest.fixture(autouse=True)
def _pin_the_clock(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: _NOW)


@pytest_asyncio.fixture
async def sessions():
    """Two sessions on the same store — standing in for two instances of the app.

    Engine caches cleared on the way *in* as well as out: ``admin_session_factory`` is lru_cached
    and binds its pool to the first loop that asks, so a driver-based test before this one leaves
    a pool bound to a dead loop.
    """
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    factory = db.admin_session_factory()
    async with factory() as writer, factory() as reader:
        yield writer, reader
    await db._admin_engine().dispose()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest.mark.asyncio
async def test_a_line_one_instance_wrote_is_read_by_another(sessions):
    """The whole point: the store is shared, so the reader never has to be the writer."""
    writer, reader = sessions
    marker = f"store.{uuid.uuid4().hex}"

    await LogRepository(writer).append([_line(marker)], instance="gw0")
    await writer.commit()

    assert [line.name for line in await LogRepository(reader).search(text=marker)] == [marker]


@pytest.mark.asyncio
async def test_a_line_carrying_unserializable_values_still_lands(sessions):
    """Regression: ``queue.task_retrying`` binds ``task_id`` as a ``UUID`` object; the engine's
    default JSON encoding refused it, and the drain wrote the whole batch off to the day files —
    the store missed exactly the tracebacks it exists to show."""
    writer, reader = sessions
    marker = f"store.{uuid.uuid4().hex}"

    line = _line(marker, task_id=uuid.uuid7(), seen_at=_NOW, exc=ValueError("boom"))
    await LogRepository(writer).append([line], instance="gw0")
    await writer.commit()

    assert [found.name for found in await LogRepository(reader).search(text=marker)] == [marker]


@pytest.mark.asyncio
async def test_a_line_names_the_instance_that_wrote_it(sessions):
    """One store, N writers — a line that cannot say which process it came from makes an outage
    on a single instance indistinguishable from one everywhere."""
    writer, reader = sessions
    marker = f"store.{uuid.uuid4().hex}"

    await LogRepository(writer).append([_line(marker)], instance="gw7")
    await writer.commit()

    found = await LogRepository(reader).search(text=marker)
    assert [line.instance for line in found] == ["gw7"]


@pytest.mark.asyncio
async def test_retention_drops_what_is_past_the_window(sessions):
    """The delete the module promised and never performed."""
    writer, reader = sessions
    marker = f"store.{uuid.uuid4().hex}"
    stale, fresh = _NOW - timedelta(days=40), _NOW

    both = [_line(marker, ts=stale), _line(marker, ts=fresh)]
    await LogRepository(writer).append(both, instance="gw0")
    await writer.commit()
    await LogRepository(writer).purge(retention_days=30)
    await writer.commit()

    kept = await LogRepository(reader).search(text=marker, window=None)
    assert [line.ts for line in kept] == [fresh]


@pytest.mark.asyncio
async def test_retention_drops_a_whole_day_as_one_partition(sessions):
    """What partitioning buys, and the reason the table is partitioned at all: a day past the
    window leaves as a ``DROP TABLE`` — instant, and leaving no dead tuples for VACUUM — instead
    of a DELETE walking one row per log line."""
    writer, _ = sessions
    old_day = (_NOW - timedelta(days=40)).date()

    await LogRepository(writer).roll(today=old_day, retention_days=30)
    await writer.commit()
    before = await _day_partitions(writer)
    await LogRepository(writer).roll(today=_NOW.date(), retention_days=30)
    await writer.commit()

    after = await _day_partitions(writer)
    assert (
        old_day.strftime("log_lines_%Y%m%d") in before,
        old_day.strftime("log_lines_%Y%m%d") in after,
    ) == (
        True,
        False,
    )


async def _day_partitions(session) -> set[str]:
    rows = await session.execute(
        sql_text(
            "SELECT c.relname FROM pg_class c JOIN pg_inherits i ON i.inhrelid = c.oid "
            "WHERE i.inhparent = 'log_lines'::regclass"
        )
    )
    return {name for (name,) in rows.all()}


# ── The filter matrix ────────────────────────────────────────────────────────────────────────
#
# Every filter the console Timeline can put on the ``logs`` source. Each test seeds its own marker
# so it never sees another's rows: the store is shared and committed, unlike the scratch directory
# the file reader used to get for free.


@pytest_asyncio.fixture
async def seeded(sessions):
    """A writer that stamps every line with one marker, and a reader narrowed to it."""
    writer, reader = sessions
    marker = f"matrix.{uuid.uuid4().hex}"

    async def seed(event: str, *, ts: datetime = _NOW, **fields) -> None:
        line = {"timestamp": ts.isoformat(), "level": "info", "event": event, **fields}
        line.setdefault("logger", marker)
        await LogRepository(writer).append([line], instance="gw0")
        await writer.commit()

    async def names(**filters) -> list[str]:
        filters.setdefault("text", marker)
        return [line.name for line in await LogRepository(reader).search(**filters)]

    return seed, names


@pytest.mark.asyncio
async def test_reads_every_line_newest_first(seeded):
    seed, names = seeded
    await seed("a.one", ts=_NOW - timedelta(hours=2))
    await seed("b.two", ts=_NOW - timedelta(hours=1))

    assert await names() == ["b.two", "a.one"]


@pytest.mark.asyncio
async def test_keeps_only_lines_at_the_named_level(seeded):
    seed, names = seeded
    await seed("kept", level="error")
    await seed("dropped", level="info")

    assert await names(level="error") == ["kept"]


@pytest.mark.asyncio
async def test_matches_the_level_whatever_the_case(seeded):
    seed, names = seeded
    await seed("kept", level="error")

    assert await names(level="ERROR") == ["kept"]


@pytest.mark.asyncio
async def test_keeps_only_lines_of_the_named_org(seeded):
    seed, names = seeded
    await seed("kept", org_id="org-1")
    await seed("dropped", org_id="org-2")

    assert await names(org_id="org-1") == ["kept"]


@pytest.mark.asyncio
async def test_keeps_only_lines_of_the_named_user(seeded):
    seed, names = seeded
    await seed("kept", user_id="user-1")
    await seed("dropped", user_id="user-2")

    assert await names(user_id="user-1") == ["kept"]


@pytest.mark.asyncio
async def test_keeps_only_lines_of_the_named_request(seeded):
    seed, names = seeded
    await seed("kept", request_id="req-1")
    await seed("dropped", request_id="req-2")

    assert await names(request_id="req-1") == ["kept"]


@pytest.mark.asyncio
async def test_text_searches_the_whole_line_not_just_its_name(seeded):
    """The needle is unique per run: unlike the scratch directory the file reader got for free,
    the store is shared and committed, so a plain word would match every earlier run's rows."""
    seed, names = seeded
    needle = f"needle-{uuid.uuid4().hex}"
    await seed("kept", detail=f"a {needle} in the payload")
    await seed("dropped", detail="nothing of the sort")

    assert await names(text=needle) == ["kept"]


@pytest.mark.asyncio
async def test_from_dt_reaches_past_the_default_window(seeded):
    """What the file window could not do. Its floor *was* the retention horizon, so ``from_dt``
    could only tighten it; the store holds what is being asked for, so a date filter wins."""
    seed, names = seeded
    await seed("kept", ts=_NOW - timedelta(days=9))

    assert await names(from_dt=_NOW - timedelta(days=10)) == ["kept"]


@pytest.mark.asyncio
async def test_the_default_window_bounds_an_unfiltered_read(seeded):
    seed, names = seeded
    await seed("kept")
    await seed("dropped", ts=_NOW - timedelta(days=9))

    assert await names() == ["kept"]


@pytest.mark.asyncio
async def test_to_dt_caps_the_newest_end(seeded):
    seed, names = seeded
    await seed("kept", ts=_NOW - timedelta(hours=2))
    await seed("dropped", ts=_NOW - timedelta(minutes=1))

    assert await names(to_dt=_NOW - timedelta(hours=1)) == ["kept"]


@pytest.mark.asyncio
async def test_limit_keeps_the_newest_of_what_matched(seeded):
    seed, names = seeded
    await seed("oldest", ts=_NOW - timedelta(hours=3))
    await seed("middle", ts=_NOW - timedelta(hours=2))
    await seed("newest", ts=_NOW - timedelta(hours=1))

    assert await names(limit=2) == ["newest", "middle"]


@pytest.mark.asyncio
async def test_promotes_the_reserved_keys_and_leaves_the_rest_in_the_payload(seeded, sessions):
    """The store is shared and committed, so this asks for an org no other test seeds — the
    marker discipline the other tests get from ``names`` does not reach a direct read."""
    seed, _ = seeded
    _, reader = sessions
    org = f"org-{uuid.uuid4().hex}"
    await seed("shape", org_id=org, user_id="user-1", request_id="req-1", detail="extra")

    found = await LogRepository(reader).search(org_id=org)

    assert [(f.org_id, f.user_id, f.request_id, f.payload) for f in found] == [
        (org, "user-1", "req-1", {"detail": "extra"})
    ]


@pytest.mark.asyncio
async def test_an_empty_filter_value_filters_nothing(seeded):
    """The Timeline builds these from URL query params, where an untouched field arrives as ""."""
    seed, names = seeded
    await seed("kept", level="info", org_id="org-1")

    assert await names(level="", org_id="", user_id="", request_id="") == ["kept"]
