from tests.e2e.drivers.protocols import BrowserProtocol


class ConsoleBrowserMixin(BrowserProtocol):
    def visit_console(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/console", wait_until="load")

    def visit_console_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/console", wait_until="load")
