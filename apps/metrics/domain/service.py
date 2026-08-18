"""Pure aggregation: flushed rows → per-route loads and screen totals.

Percentiles come from the histogram buckets, linearly interpolated inside the
bucket where the cumulative count crosses the quantile — exactly how Prometheus'
``histogram_quantile`` computes them. That is what makes sums across rows/instances
legitimate, and it keeps p95 off the bucket bounds (a raw upper bound would report
every latency as one of 5/10/25/50/100/250/500…, and always the bucket ceiling).
"""

from datetime import datetime

from apps.metrics.domain.models import LoadPoint, LoadTotals, RequestMetric, RouteLoad
from apps.shared.observability.metrics import BUCKET_BOUNDS_MS


def percentile_ms(bucket_counts: list[int], quantile: float = 0.95) -> float | None:
    total = sum(bucket_counts)
    if total == 0:
        return None
    rank = quantile * total
    cumulative = 0
    lower = 0.0  # lower edge of the current bucket (previous bound, 0 for the first)
    for bound, count in zip(BUCKET_BOUNDS_MS, bucket_counts, strict=False):
        if cumulative + count >= rank:
            # The rank lands in this finite bucket (lower, bound]. Assume the
            # observations are spread uniformly across it and interpolate.
            return lower + (bound - lower) * (rank - cumulative) / count
        cumulative += count
        lower = bound
    return None  # rank lands in the +Inf bucket — slower than the largest bound


def _error_rate(errors: int, requests: int) -> float:
    return round(100 * errors / requests, 1) if requests else 0.0


def _mean_ms(duration_sum_ms: float, requests: int) -> float | None:
    """The true, unbucketed average — a sanity check next to the interpolated p95."""
    return duration_sum_ms / requests if requests else None


def _merged_buckets(rows: list[RequestMetric]) -> list[int]:
    merged = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    for row in rows:
        for i, count in enumerate(row.duration_buckets):
            merged[i] += count
    return merged


def timeseries(rows: list[RequestMetric]) -> list[LoadPoint]:
    """Collapse rows to one point per time bucket, chronological — for the load chart."""
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
    """Sum rows (any resolution, any instance) per route; busiest routes first."""
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
