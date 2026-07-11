from apps.metrics.tests.e2e.driver_mixin_api import seeded_metric
from tests.e2e.drivers.browser_base import BrowserBase


class MetricsBrowserMixin(BrowserBase):
    def seed_traffic(self, label: str, requests: int, errors: int, around_ms: int) -> None:
        seed = getattr(self, "_seed", None)  # learning mixin
        assert seed is not None

        async def _do(s):
            s.add(seeded_metric(label, requests, errors, around_ms))
            await s.flush()

        seed(_do)

    def open_load_screen(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()
        self.page.goto(f"{self.base_url}/console/load", wait_until="load")

    def _route_row(self, label: str):
        return self.page.locator(f"[data-load-route='{label}']")

    def assert_route_load(self, label: str, requests: int, rate_pct: int) -> None:
        row = self._route_row(label)
        row.wait_for(timeout=5000)
        shown = row.locator("[data-load-requests]").inner_text().strip()
        assert shown == str(requests), f"expected {requests} requests, got {shown!r}"
        errors = row.locator("[data-load-errors]").inner_text().strip()
        assert errors == f"{rate_pct}%", f"expected {rate_pct}%, got {errors!r}"

    def assert_route_p95(self, label: str, p95_ms: int) -> None:
        shown = self._route_row(label).locator("[data-load-p95]").inner_text().strip()
        assert shown == f"{p95_ms} ms", f"expected p95 {p95_ms} ms, got {shown!r}"

    def assert_load_screen_empty(self) -> None:
        self.page.wait_for_selector("[data-load-empty]", timeout=5000)

    def fetch_metrics_exposition(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()
        self.page.goto(f"{self.base_url}/metrics", wait_until="load")

    def assert_exposition_reports_console_route(self) -> None:
        text = self.page.inner_text("body")
        assert "http_requests_total" in text
        assert 'route="/console"' in text, f"/console not measured:\n{text[:500]}"

    def try_open_load_screen(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/console/load")

    def try_fetch_metrics_exposition(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/metrics")
