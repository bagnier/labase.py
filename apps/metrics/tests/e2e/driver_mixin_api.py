from apps.metrics.domain.models import MetricResolution, RequestMetric
from apps.shared import clock
from apps.shared.observability.metrics import BUCKET_BOUNDS_MS, bucket_index
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.api_base import ApiBase


def seeded_metric(label: str, requests: int, errors: int, around_ms: int) -> RequestMetric:
    method, route = label.split(" ", 1)
    buckets = [0] * (len(BUCKET_BOUNDS_MS) + 1)
    buckets[bucket_index(around_ms)] = requests
    return RequestMetric(
        bucket=clock.now().replace(second=0, microsecond=0),
        resolution=MetricResolution.minute,
        instance="seed",
        method=method,
        route=route,
        requests=requests,
        errors=errors,
        duration_sum_ms=float(requests * around_ms),
        duration_buckets=buckets,
    )


class MetricsApiMixin(ApiBase):
    def seed_traffic(self, label: str, requests: int, errors: int, around_ms: int) -> None:
        async def _do(s):
            s.add(seeded_metric(label, requests, errors, around_ms))
            await s.flush()

        self.run(db.seed_fixtures(_do))

    def _metrics_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def open_load_screen(self) -> None:
        self._metrics_as_admin()
        self.response = self.client().get("/console/load", headers={"accept": "application/json"})
        assert self.response.status_code == 200, (
            f"GET /console/load: {self.response.status_code} {self.response.text}"
        )

    def _route_load(self, label: str) -> dict:
        assert self.response is not None
        routes = self.response.json()["routes"]
        load = next((r for r in routes if r["label"] == label), None)
        assert load is not None, f"no route {label!r}: {routes}"
        return load

    def assert_route_load(self, label: str, requests: int, rate_pct: int) -> None:
        load = self._route_load(label)
        assert load["requests"] == requests, f"expected {requests}, got {load['requests']}"
        assert int(load["error_rate_pct"]) == rate_pct, f"got {load['error_rate_pct']}%"

    def assert_route_p95(self, label: str, p95_ms: int) -> None:
        load = self._route_load(label)
        assert round(load["p95_ms"]) == p95_ms, f"expected p95 {p95_ms}, got {load['p95_ms']}"

    def assert_route_avg(self, label: str, avg_ms: int) -> None:
        load = self._route_load(label)
        assert round(load["avg_ms"]) == avg_ms, f"expected avg {avg_ms}, got {load['avg_ms']}"

    def assert_load_screen_empty(self) -> None:
        assert self.response is not None
        body = self.response.json()
        assert body["routes"] == [], f"expected no routes: {body['routes']}"
        assert body["totals"]["requests"] == 0

    def fetch_metrics_exposition(self) -> None:
        self._metrics_as_admin()
        self.response = self.client().get("/metrics", headers={"accept": "text/plain"})
        assert self.response.status_code == 200, f"GET /metrics: {self.response.status_code}"

    def assert_exposition_reports_console_route(self) -> None:
        assert self.response is not None
        text = self.response.text
        assert "http_requests_total" in text
        assert 'route="/console"' in text, f"/console not measured:\n{text}"

    def try_open_load_screen(self) -> None:
        self.response = self.client().get("/console/load", headers={"accept": "application/json"})

    def try_fetch_metrics_exposition(self) -> None:
        self.response = self.client().get("/metrics", headers={"accept": "text/plain"})
