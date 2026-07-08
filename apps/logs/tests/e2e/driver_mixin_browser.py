from tests.e2e.drivers.browser_base import BrowserBase


class LogsBrowserMixin(BrowserBase):
    def _logs_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def open_logs_screen(self) -> None:
        self._logs_as_admin()
        self.page.goto(f"{self.base_url}/console/logs", wait_until="load")

    def assert_logs_empty(self) -> None:
        self.page.wait_for_selector("[data-logs-empty]", timeout=5000)

    def try_open_logs_screen(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/console/logs")

    def assert_logs_not_found(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 404, f"Expected 404, got {self.last_response.status}"
