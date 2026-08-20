from datetime import UTC, datetime

from apps.metrics.domain.models import MetricResolution, RequestMetric
from apps.metrics.domain.service import aggregate, percentile_ms, timeseries
from apps.shared.metrics import BUCKET_BOUNDS_MS


def _buckets(**at_ms: int) -> list[int]:
    buckets = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    for ms, count in at_ms.items():
        bound = float(ms.removeprefix("ms_"))
        buckets[BUCKET_BOUNDS_MS.index(bound)] = count
    return buckets


def _row(method: str, route: str, requests: int, errors: int, buckets: list[int]):
    return RequestMetric(
        bucket_start=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        resolution=MetricResolution.minute,
        instance="test",
        method=method,
        route=route,
        requests=requests,
        errors=errors,
        duration_sum_ms=0.0,
        duration_buckets=buckets,
    )


def test_percentile_interpolates_inside_the_crossing_bucket():
    """30 observations in the (50, 100] bucket: p95 sits 95% of the way up it. rank = 0.95 * 30 =
    28.5 → 50 + (100-50) * 28.5/30 = 97.5, not a bare 100."""
    assert percentile_ms(_buckets(ms_100=30)) == 97.5
    # 95 fast + 5 slow: rank 95 lands exactly on the (10, 25] bucket's top edge.
    assert percentile_ms(_buckets(ms_25=95, ms_5000=5)) == 25
    # one more slow observation tips p95 into the (2500, 5000] bucket, near its floor.
    assert percentile_ms(_buckets(ms_25=94, ms_5000=6)) == 2500 + 2500 / 6


def test_percentile_edge_cases():
    assert percentile_ms([0] * (len(BUCKET_BOUNDS_MS) + 1)) is None
    only_inf = [0] * len(BUCKET_BOUNDS_MS) + [3]
    assert percentile_ms(only_inf) is None  # slower than the largest bound


def test_aggregate_sums_rows_across_instances_and_sorts_by_volume():
    rows = [
        _row("GET", "/todo", 20, 2, _buckets(ms_100=20)),
        _row("GET", "/todo", 10, 1, _buckets(ms_100=10)),  # second instance/minute
        _row("POST", "/todo", 40, 0, _buckets(ms_25=40)),
    ]
    loads, totals = aggregate(rows)

    assert [load.label for load in loads] == ["POST /todo", "GET /todo"]
    get_todo = loads[1]
    assert get_todo.requests == 30
    assert get_todo.errors == 3
    assert get_todo.error_rate_pct == 10.0
    assert get_todo.p95_ms == 97.5  # 30 obs in (50,100] → interpolated, not the 100 ceiling
    assert totals.requests == 70
    assert totals.error_rate_pct == round(100 * 3 / 70, 1)


def test_aggregate_empty_window():
    loads, totals = aggregate([])
    assert loads == []
    assert totals.requests == 0
    assert totals.error_rate_pct == 0.0
    assert totals.p95_ms is None


def _row_at(minute: int, requests: int, errors: int) -> RequestMetric:
    row = _row("GET", "/todo", requests, errors, _buckets(ms_100=requests))
    row.bucket_start = datetime(2026, 7, 6, 12, minute, tzinfo=UTC)
    return row


def test_timeseries_sums_per_bucket_across_routes_and_sorts_chronologically():
    rows = [
        _row_at(2, 10, 1),
        _row_at(0, 20, 0),  # earliest bucket, defined last
        _row_at(2, 5, 2),  # same bucket as the first row → summed
    ]
    points = timeseries(rows)

    assert [p.bucket_start.minute for p in points] == [0, 2]
    assert [(p.requests, p.errors) for p in points] == [(20, 0), (15, 3)]


def test_timeseries_empty_window():
    assert timeseries([]) == []
