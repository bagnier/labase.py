"""Writes are single-writer by construction (one flusher per process, keyed by
its instance id; rollup runs on the task queue's claimed row), so merge-on-write
is a plain read-modify-write — no upsert gymnastics over int[] columns.
"""

from datetime import datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.metrics.domain.models import MetricResolution, RequestMetric
from apps.shared import clock
from apps.shared.observability.metrics import MetricsSnapshot


async def _merge_row(
    session: AsyncSession,
    *,
    bucket: datetime,
    resolution: MetricResolution,
    instance: str,
    method: str,
    route: str,
    requests: int,
    errors: int,
    duration_sum_ms: float,
    duration_buckets: list[int],
) -> None:
    existing = await session.scalar(
        select(RequestMetric).where(
            RequestMetric.bucket == bucket,
            RequestMetric.resolution == resolution,
            RequestMetric.instance == instance,
            RequestMetric.method == method,
            RequestMetric.route == route,
        )
    )
    if existing is None:
        session.add(
            RequestMetric(
                bucket=bucket,
                resolution=resolution,
                instance=instance,
                method=method,
                route=route,
                requests=requests,
                errors=errors,
                duration_sum_ms=duration_sum_ms,
                duration_buckets=duration_buckets,
            )
        )
    else:
        existing.requests += requests
        existing.errors += errors
        existing.duration_sum_ms += duration_sum_ms
        existing.duration_buckets = [
            mine + theirs
            for mine, theirs in zip(existing.duration_buckets, duration_buckets, strict=True)
        ]
    await session.flush()


async def add_deltas(
    session: AsyncSession, *, instance: str, bucket: datetime, deltas: MetricsSnapshot
) -> None:
    """Fold one flush's deltas into their minute rows."""
    for (method, route), stats in deltas.items():
        await _merge_row(
            session,
            bucket=bucket,
            resolution=MetricResolution.minute,
            instance=instance,
            method=method,
            route=route,
            requests=stats.requests,
            errors=stats.errors,
            duration_sum_ms=stats.duration_sum_ms,
            duration_buckets=stats.buckets,
        )


async def window_rows(session: AsyncSession, since: datetime) -> list[RequestMetric]:
    return list(await session.scalars(select(RequestMetric).where(RequestMetric.bucket >= since)))


async def total_requests(session: AsyncSession, since: datetime) -> int:
    return (
        await session.scalar(
            select(func.coalesce(func.sum(RequestMetric.requests), 0)).where(
                RequestMetric.bucket >= since
            )
        )
        or 0
    )


async def rollup(session: AsyncSession, *, minute_retention_days: int) -> tuple[int, int]:
    """Downsample: minute rows past the window collapse into hour rows.

    Instances collapse too — per-instance detail only matters while recent.
    Returns (minute rows removed, hour rows touched).
    """
    cutoff = clock.now() - timedelta(days=minute_retention_days)
    stale = list(
        await session.scalars(
            select(RequestMetric).where(
                RequestMetric.resolution == MetricResolution.minute,
                RequestMetric.bucket < cutoff,
            )
        )
    )
    merged: dict[tuple[datetime, str, str], list[RequestMetric]] = {}
    for row in stale:
        hour = row.bucket.replace(minute=0, second=0, microsecond=0)
        merged.setdefault((hour, row.method, row.route), []).append(row)
    for (hour, method, route), rows in merged.items():
        buckets = [0] * len(rows[0].duration_buckets)
        for row in rows:
            for i, count in enumerate(row.duration_buckets):
                buckets[i] += count
        await _merge_row(
            session,
            bucket=hour,
            resolution=MetricResolution.hour,
            instance="*",
            method=method,
            route=route,
            requests=sum(r.requests for r in rows),
            errors=sum(r.errors for r in rows),
            duration_sum_ms=sum(r.duration_sum_ms for r in rows),
            duration_buckets=buckets,
        )
    for row in stale:
        await session.delete(row)
    await session.flush()
    return len(stale), len(merged)


async def purge(session: AsyncSession, retention_days: int) -> int:
    """Drop hour rows past the admin-tunable retention window."""
    deleted = await session.scalar(
        text(
            "WITH purged AS ("
            "  DELETE FROM request_metrics"
            "  WHERE resolution = 'hour'"
            "    AND bucket < now() - make_interval(days => :days) RETURNING 1"
            ") SELECT count(*) FROM purged"
        ),
        {"days": retention_days},
    )
    return int(deleted or 0)
