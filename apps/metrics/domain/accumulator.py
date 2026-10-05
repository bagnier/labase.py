"""The process's request counters, fed by ``RequestLogger``. ``/metrics`` reads them cumulative;
the ``MetricsFlusher`` persists the deltas between snapshots, one row per route and minute.

Labels stay few: the route template, the method (outside ``KNOWN_METHODS``: ``OTHER_METHOD``) and
the status class. An unmatched path keeps its own label up to ``UNMATCHED_LABEL_CAP``, then
collapses into ``unmatched``.
"""

from dataclasses import dataclass, field

# Histogram bounds in ms; ``+Inf`` is the implicit last slot.
BUCKET_BOUNDS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
UNMATCHED_ROUTE = "unmatched"
# A safety net: only our own dead links reach here, a handful.
UNMATCHED_LABEL_CAP = 25
# Our routes' verbs, plus HEAD and OPTIONS answered by Starlette.
KNOWN_METHODS: frozenset[str] = frozenset(
    {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}
)
OTHER_METHOD = "OTHER"


def _empty_buckets() -> list[int]:
    return [0] * (len(BUCKET_BOUNDS_MS) + 1)


@dataclass
class RouteStats:
    by_status: dict[str, int] = field(default_factory=dict)  # "2xx": count
    buckets: list[int] = field(default_factory=_empty_buckets)
    duration_sum_ms: float = 0.0

    @property
    def requests(self) -> int:
        return sum(self.by_status.values())

    @property
    def errors(self) -> int:
        return self.by_status.get("5xx", 0)

    def copy(self) -> RouteStats:
        return RouteStats(
            by_status=dict(self.by_status),
            buckets=list(self.buckets),
            duration_sum_ms=self.duration_sum_ms,
        )


MetricsSnapshot = dict[tuple[str, str], RouteStats]


def bucket_index(duration_ms: float) -> int:
    for i, bound in enumerate(BUCKET_BOUNDS_MS):
        if duration_ms <= bound:
            return i
    return len(BUCKET_BOUNDS_MS)


class MetricsAccumulator:
    def __init__(self) -> None:
        self._stats: MetricsSnapshot = {}
        self._unmatched_paths: set[str] = set()

    def observe(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_ms: float,
        *,
        unmatched: bool = False,
    ) -> None:
        if unmatched:
            route = self._bounded_unmatched_label(route)
        if method not in KNOWN_METHODS:
            method = OTHER_METHOD
        stats = self._stats.setdefault((method, route), RouteStats())
        status_class = f"{status_code // 100}xx"
        stats.by_status[status_class] = stats.by_status.get(status_class, 0) + 1
        stats.buckets[bucket_index(duration_ms)] += 1
        stats.duration_sum_ms += duration_ms

    def _bounded_unmatched_label(self, path: str) -> str:
        if path in self._unmatched_paths:
            return path
        if len(self._unmatched_paths) >= UNMATCHED_LABEL_CAP:
            return UNMATCHED_ROUTE
        self._unmatched_paths.add(path)
        return path

    def snapshot(self) -> MetricsSnapshot:
        return {key: stats.copy() for key, stats in self._stats.items()}

    def reset(self) -> None:
        self._stats.clear()
        self._unmatched_paths.clear()

    def render_prometheus(self) -> str:
        """Prometheus text format, cumulative since process start."""
        lines = ["# TYPE http_requests_total counter"]
        items = sorted(self._stats.items())
        for (method, route), stats in items:
            lines.extend(
                f'http_requests_total{{method="{method}",route="{route}",'
                f'status="{status_class}"}} {stats.by_status[status_class]}'
                for status_class in sorted(stats.by_status)
            )
        lines.append("# TYPE http_request_duration_seconds histogram")
        for (method, route), stats in items:
            labels = f'method="{method}",route="{route}"'
            cumulative = 0
            for bound, count in zip((*BUCKET_BOUNDS_MS, None), stats.buckets, strict=True):
                cumulative += count
                le = "+Inf" if bound is None else f"{bound / 1000:g}"
                lines.append(
                    f'http_request_duration_seconds_bucket{{{labels},le="{le}"}} {cumulative}'
                )
            lines.append(f"http_request_duration_seconds_count{{{labels}}} {stats.requests}")
            lines.append(
                f"http_request_duration_seconds_sum{{{labels}}} {stats.duration_sum_ms / 1000:g}"
            )
        return "\n".join(lines) + "\n"


def snapshot_deltas(previous: MetricsSnapshot, current: MetricsSnapshot) -> MetricsSnapshot:
    deltas: MetricsSnapshot = {}
    for key, stats in current.items():
        prev = previous.get(key, RouteStats())
        by_status = {
            status: count - prev.by_status.get(status, 0)
            for status, count in stats.by_status.items()
            if count - prev.by_status.get(status, 0)
        }
        if not by_status:
            continue
        deltas[key] = RouteStats(
            by_status=by_status,
            buckets=[c - p for c, p in zip(stats.buckets, prev.buckets, strict=True)],
            duration_sum_ms=stats.duration_sum_ms - prev.duration_sum_ms,
        )
    return deltas


accumulator = MetricsAccumulator()
