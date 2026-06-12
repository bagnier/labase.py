from tests.e2e.drivers.protocols import BrowserProtocol


class DashboardBrowserMixin(BrowserProtocol):
    def view_dashboard(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/profile", wait_until="load")

    def assert_link_to_todos(self) -> None:
        assert self._p.query_selector("a[href*='/todos']") is not None, (
            "No link to /todos found on dashboard"
        )

    def view_profile(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/profile", wait_until="load")

    def assert_link_to_org_dashboard(self) -> None:
        assert self._p.query_selector("a[href*='/dashboard']") is not None, (
            "No link to org dashboard found on profile"
        )

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "_active_org_slug", "")
        self._last_response = self._p.goto(f"{self._base_url}/{slug}/dashboard", wait_until="load")

    def assert_org_dashboard_visible(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, (
            f"Expected 200 for org dashboard, got {self._last_response.status}"
        )

    def visit_profile_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/profile", wait_until="load")

    def visit_org_dashboard_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/any-org/dashboard", wait_until="load")

    def visit_console_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/console", wait_until="load")
