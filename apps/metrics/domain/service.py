"""Flushed rows to per-route loads and screen totals.

Percentiles interpolate inside the histogram bucket where the quantile falls, like Prometheus's
``histogram_quantile``: buckets sum across rows and instances, and p95 is not stuck on a bound.
"""

from datetime import datetime

from apps.metrics.domain.accumulator import BUCKET_BOUNDS_MS
from apps.metrics.domain.models import LoadPoint, LoadTotals, RequestMetric, RouteLoad


def percentile_ms(bucket_counts: list[int], quantile: float = 0.95) -> float | None:
    total = sum(bucket_counts)
    if total == 0:
        return None
    rank = quantile * total
    cumulative = 0
    lower = 0.0
    for bound, count in zip(BUCKET_BOUNDS_MS, bucket_counts, strict=False):
        if cumulative + count >= rank:
            # Assumes the bucket's observations are spread uniformly.
            return lower + (bound - lower) * (rank - cumulative) / count
        cumulative += count
        lower = bound
    return None  # in the +Inf bucket


def _error_rate(errors: int, requests: int) -> float:
    return round(100 * errors / requests, 1) if requests else 0.0


def _mean_ms(duration_sum_ms: float, requests: int) -> float | None:
    """The exact average, beside the interpolated p95."""
    return duration_sum_ms / requests if requests else None


def _merged_buckets(rows: list[RequestMetric]) -> list[int]:
    merged = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    for row in rows:
        for i, count in enumerate(row.duration_buckets):
            merged[i] += count
    return merged


def timeseries(rows: list[RequestMetric]) -> list[LoadPoint]:
    """One point per time bucket, chronological."""
    by_bucket: dict[datetime, LoadPoint] = {}
    for row in rows:
        point = by_bucket.get(row.bucket_start)
        if point is None:
            by_bucket[row.bucket_start] = LoadPoint(
                bucket_start=row.bucket_start, requests=row.requests, errors=row.errors
            )
        else:
            point.requests += row.requests
            point.errors += row.errors
    return [by_bucket[bucket] for bucket in sorted(by_bucket)]


def aggregate(rows: list[RequestMetric]) -> tuple[list[RouteLoad], LoadTotals]:
    """Rows summed per route, busiest first."""
    by_route: dict[tuple[str, str], list[RequestMetric]] = {}
    for row in rows:
        by_route.setdefault((row.method, row.route), []).append(row)

    loads = []
    for (method, route), group in by_route.items():
        requests = sum(r.requests for r in group)
        errors = sum(r.errors for r in group)
        loads.append(
            RouteLoad(
                method=method,
                route=route,
                label=f"{method} {route}",
                requests=requests,
                errors=errors,
                error_rate_pct=_error_rate(errors, requests),
                avg_ms=_mean_ms(sum(r.duration_sum_ms for r in group), requests),
                p95_ms=percentile_ms(_merged_buckets(group)),
            )
        )
    loads.sort(key=lambda load: load.requests, reverse=True)

    total_requests = sum(load.requests for load in loads)
    total_errors = sum(load.errors for load in loads)
    totals = LoadTotals(
        requests=total_requests,
        error_rate_pct=_error_rate(total_errors, total_requests),
        avg_ms=_mean_ms(sum(r.duration_sum_ms for r in rows), total_requests),
        p95_ms=percentile_ms(_merged_buckets(rows)),
    )
    return loads, totals
