"""The flusher persists deltas; the rollup downsamples and purges."""

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from apps.metrics.domain.accumulator import BUCKET_BOUNDS_MS, accumulator
from apps.metrics.domain.models import MetricResolution, RequestMetric
from apps.metrics.infra.flusher import MetricsFlusher
from apps.metrics.infra.repository import purge, rollup
from apps.shared import clock
from apps.shared.persistence import database as db

MARKER_ROUTE = "/metrics-flush-test"


def _clear_engine_caches() -> None:
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest_asyncio.fixture(autouse=True)
async def metrics_isolation(monkeypatch):
    _clear_engine_caches()
    # A pinned clock: several clock.now() calls could straddle a minute or hour boundary.
    monkeypatch.setattr(clock, "now", lambda: datetime(2024, 1, 15, 12, 0, tzinfo=UTC))
    yield
    async with db.admin_session_factory()() as session:
        await session.execute(
            delete(RequestMetric).where(RequestMetric.route.like(f"{MARKER_ROUTE}%"))
        )
        await session.commit()
    await db._admin_engine().dispose()
    _clear_engine_caches()


async def _rows(route: str) -> list[RequestMetric]:
    async with db.admin_session_factory()() as session:
        return list(
            await session.scalars(select(RequestMetric).where(RequestMetric.route == route))
        )


@pytest.mark.asyncio
async def test_flusher_persists_deltas_and_merges_within_a_minute():
    flusher = MetricsFlusher(interval_seconds=0)
    # The accumulator is process-global: baseline on it, ignoring other tests' traffic.
    flusher._previous = accumulator.snapshot()
    accumulator.observe("GET", MARKER_ROUTE, 200, 80)
    accumulator.observe("GET", MARKER_ROUTE, 500, 30)
    await flusher.tick()

    (row,) = await _rows(MARKER_ROUTE)
    assert row.requests == 2
    assert row.errors == 1
    assert row.resolution == MetricResolution.minute

    accumulator.observe("GET", MARKER_ROUTE, 200, 80)
    await flusher.tick()  # merged into the same minute row

    (row,) = await _rows(MARKER_ROUTE)
    assert row.requests == 3

    await flusher.tick()
    (row,) = await _rows(MARKER_ROUTE)
    assert row.requests == 3


@pytest.mark.asyncio
async def test_stopping_the_flusher_persists_the_interval_it_was_holding():
    """Every deploy stops the process: the interval since the last tick must not be lost."""
    route = f"{MARKER_ROUTE}-shutdown"
    flusher = MetricsFlusher(interval_seconds=0)
    flusher._previous = accumulator.snapshot()
    accumulator.observe("GET", route, 200, 40)

    await flusher.stop()

    assert [(row.route, row.requests) for row in await _rows(route)] == [(route, 1)]


@pytest.mark.asyncio
async def test_rollup_downsamples_old_minute_rows_then_purge_applies_retention():
    route = f"{MARKER_ROUTE}-rollup"
    old = clock.now() - timedelta(days=10)
    buckets = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    buckets[4] = 5
    async with db.admin_session_factory()() as session:
        for minute in (old, old + timedelta(minutes=1)):
            session.add(
                RequestMetric(
                    bucket_start=minute,
                    resolution=MetricResolution.minute,
                    instance="a",
                    method="GET",
                    route=route,
                    requests=5,
                    errors=1,
                    duration_sum_ms=400.0,
                    duration_buckets=buckets,
                )
            )
        await session.commit()

    async with db.admin_session_factory()() as session:
        removed, merged = await rollup(session, minute_retention_days=7)
        await session.commit()
    assert removed == 2
    assert merged == 1

    (row,) = await _rows(route)
    assert row.resolution == MetricResolution.hour
    assert row.requests == 10
    assert row.errors == 2
    assert row.duration_buckets[4] == 10

    async with db.admin_session_factory()() as session:
        purged = await purge(session, retention_days=7)
        await session.commit()
    assert purged == 1
    assert await _rows(route) == []
