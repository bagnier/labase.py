from tests.e2e.drivers.protocols import BrowserProtocol


class DashboardBrowserMixin(BrowserProtocol):
    def view_dashboard(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/dashboard", wait_until="load")

    def assert_link_to_todos(self) -> None:
        assert self._p.query_selector("a[href*='/todos']") is not None, (
            "No link to /todos found on dashboard"
        )
