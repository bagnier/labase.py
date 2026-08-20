"""In-memory HTTP metrics — the single collector of the load-metrics brick.

``RequestLogger`` feeds one process-wide :class:`MetricsAccumulator`; two readers
share it (collection is written once):

- the ``/metrics`` Prometheus exposition reads the **cumulative** counters live;
- the ``MetricsFlusher`` (apps/metrics) diffs successive :meth:`snapshot` calls
  and persists **deltas**, one row per (route, minute) — never one per request.

Labels stay low-cardinality by design: route *template* (``/{org_handle}/todos``,
not the expanded path), method, status class. A request that matched no route is
recorded under its real path (so a dead link from ourselves is identifiable), but
only up to ``UNMATCHED_LABEL_CAP`` distinct paths — the overflow collapses into
``unmatched`` so nothing can explode the label set. And only 4xx worth an admin's
eyes reach here at all: ``RequestLogger`` gates them to internal dead links, so bot
scans, the favicon probe and ``/.well-known`` browser probes never feed the
accumulator (see ``_feeds_load_metrics``).
"""

from dataclasses import dataclass, field

# Fixed histogram boundaries, in milliseconds. p50/p95 are derived from the bucket counts,
# Prometheus-style; the ``+Inf`` bucket is the implicit last slot of ``buckets``.
BUCKET_BOUNDS_MS: tuple[float, ...] = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)
UNMATCHED_ROUTE = "unmatched"
# How many distinct no-route paths keep their real label before overflow collapses them into
# ``unmatched``. A safety net only: what is recordable is already gated to our own dead links, a
# handful, so this caps nothing but a same-host-referer scanner.
UNMATCHED_LABEL_CAP = 25


def _empty_buckets() -> list[int]:
    return [0] * (len(BUCKET_BOUNDS_MS) + 1)


@dataclass
class RouteStats:
    """Counters for one (method, route template) pair."""

    by_status: dict[str, int] = field(default_factory=dict)  # "2xx" → count
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
        stats = self._stats.setdefault((method, route), RouteStats())
        status_class = f"{status_code // 100}xx"
        stats.by_status[status_class] = stats.by_status.get(status_class, 0) + 1
        stats.buckets[bucket_index(duration_ms)] += 1
        stats.duration_sum_ms += duration_ms

    def _bounded_unmatched_label(self, path: str) -> str:
        """The real path while under the cap; the collapsed ``unmatched`` bucket beyond it."""
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
        """Standard text exposition — cumulative counters since process start."""
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
    """What happened between two snapshots — the flusher's write set."""
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
