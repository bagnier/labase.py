from apps.shared.observability.metrics import (
    BUCKET_BOUNDS_MS,
    MetricsAccumulator,
    RouteStats,
    bucket_index,
    snapshot_deltas,
)


def test_observe_counts_by_status_class_and_bucket():
    acc = MetricsAccumulator()
    acc.observe("GET", "/todo", 200, 80)
    acc.observe("GET", "/todo", 200, 80)
    acc.observe("GET", "/todo", 500, 2000)

    stats = acc.snapshot()[("GET", "/todo")]
    assert stats.requests == 3
    assert stats.errors == 1
    assert stats.by_status == {"2xx": 2, "5xx": 1}
    assert stats.buckets[bucket_index(80)] == 2
    assert stats.buckets[bucket_index(2000)] == 1
    assert stats.duration_sum_ms == 2160


def test_bucket_index_covers_bounds_and_overflow():
    assert bucket_index(0) == 0
    assert bucket_index(5) == 0
    assert bucket_index(5.1) == 1
    assert bucket_index(10001) == len(BUCKET_BOUNDS_MS)  # +Inf slot


def test_snapshot_is_isolated_from_later_observations():
    acc = MetricsAccumulator()
    acc.observe("GET", "/todo", 200, 10)
    snap = acc.snapshot()
    acc.observe("GET", "/todo", 200, 10)
    assert snap[("GET", "/todo")].requests == 1


def test_snapshot_deltas_returns_only_what_changed():
    acc = MetricsAccumulator()
    acc.observe("GET", "/a", 200, 10)
    acc.observe("GET", "/b", 200, 10)
    before = acc.snapshot()
    acc.observe("GET", "/b", 500, 300)
    acc.observe("POST", "/c", 201, 20)

    deltas = snapshot_deltas(before, acc.snapshot())
    assert set(deltas) == {("GET", "/b"), ("POST", "/c")}
    assert deltas[("GET", "/b")].by_status == {"5xx": 1}
    assert deltas[("GET", "/b")].duration_sum_ms == 300
    assert deltas[("POST", "/c")].requests == 1


def test_snapshot_deltas_empty_when_idle():
    acc = MetricsAccumulator()
    acc.observe("GET", "/a", 200, 10)
    snap = acc.snapshot()
    assert snapshot_deltas(snap, acc.snapshot()) == {}


def test_render_prometheus_exposes_cumulative_histogram():
    acc = MetricsAccumulator()
    acc.observe("GET", "/console", 200, 80)
    acc.observe("GET", "/console", 200, 90)
    acc.observe("GET", "/console", 500, 30)

    text = acc.render_prometheus()
    assert 'http_requests_total{method="GET",route="/console",status="2xx"} 2' in text
    assert 'http_requests_total{method="GET",route="/console",status="5xx"} 1' in text
    # buckets are cumulative: the 30ms hit shows up from le=0.05 onwards
    assert 'le="0.05"} 1' in text
    assert 'le="0.1"} 3' in text
    assert 'le="+Inf"} 3' in text
    assert 'http_request_duration_seconds_count{method="GET",route="/console"} 3' in text
    assert text.endswith("\n")


def test_route_stats_copy_is_deep_enough():
    stats = RouteStats()
    clone = stats.copy()
    clone.by_status["2xx"] = 1
    clone.buckets[0] = 1
    assert stats.by_status == {}
    assert stats.buckets[0] == 0
