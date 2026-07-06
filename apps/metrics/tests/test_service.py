from datetime import UTC, datetime

from apps.metrics.domain.models import MetricResolution, RequestMetric
from apps.metrics.domain.service import aggregate, percentile_ms
from apps.shared.observability.metrics import BUCKET_BOUNDS_MS


def _buckets(**at_ms: int) -> list[int]:
    buckets = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    for ms, count in at_ms.items():
        bound = float(ms.removeprefix("ms_"))
        buckets[BUCKET_BOUNDS_MS.index(bound)] = count
    return buckets


def _row(method: str, route: str, requests: int, errors: int, buckets: list[int]):
    return RequestMetric(
        bucket=datetime(2026, 7, 6, 12, 0, tzinfo=UTC),
        resolution=MetricResolution.minute,
        instance="test",
        method=method,
        route=route,
        requests=requests,
        errors=errors,
        duration_sum_ms=0.0,
        duration_buckets=buckets,
    )


def test_percentile_is_the_bucket_upper_bound():
    # 30 observations ≤100ms: the 95th percentile lands in the 100ms bucket.
    assert percentile_ms(_buckets(ms_100=30)) == 100
    # 95 fast + 5 slow: p95 still inside the fast bucket (ceil(0.95*100)=95).
    assert percentile_ms(_buckets(ms_25=95, ms_5000=5)) == 25
    # one more slow observation tips it over
    assert percentile_ms(_buckets(ms_25=94, ms_5000=6)) == 5000


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
    assert get_todo.p95_ms == 100
    assert totals.requests == 70
    assert totals.error_rate_pct == round(100 * 3 / 70, 1)


def test_aggregate_empty_window():
    loads, totals = aggregate([])
    assert loads == []
    assert totals.requests == 0
    assert totals.error_rate_pct == 0.0
    assert totals.p95_ms is None
