"""Pure aggregation: flushed rows → per-route loads and screen totals.

Percentiles come from the histogram buckets (upper bound of the bucket where the
cumulative count crosses the quantile), exactly how Prometheus computes them —
that is what makes sums across rows/instances legitimate.
"""

import math

from apps.metrics.domain.models import LoadTotals, RequestMetric, RouteLoad
from apps.shared.observability.metrics import BUCKET_BOUNDS_MS


def percentile_ms(bucket_counts: list[int], quantile: float = 0.95) -> float | None:
    total = sum(bucket_counts)
    if total == 0:
        return None
    threshold = math.ceil(quantile * total)
    cumulative = 0
    for bound, count in zip(BUCKET_BOUNDS_MS, bucket_counts, strict=False):
        cumulative += count
        if cumulative >= threshold:
            return bound
    return None  # only +Inf observations — slower than the largest bound


def _merged_buckets(rows: list[RequestMetric]) -> list[int]:
    merged = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    for row in rows:
        for i, count in enumerate(row.duration_buckets):
            merged[i] += count
    return merged


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
                error_rate_pct=round(100 * errors / requests, 1) if requests else 0.0,
                p95_ms=percentile_ms(_merged_buckets(group)),
            )
        )
    loads.sort(key=lambda load: load.requests, reverse=True)

    total_requests = sum(load.requests for load in loads)
    total_errors = sum(load.errors for load in loads)
    totals = LoadTotals(
        requests=total_requests,
        error_rate_pct=round(100 * total_errors / total_requests, 1) if total_requests else 0.0,
        p95_ms=percentile_ms(_merged_buckets(rows)),
    )
    return loads, totals
