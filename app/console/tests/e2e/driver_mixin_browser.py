from tests.e2e.drivers.browser_base import BrowserBase


class ConsoleBrowserMixin(BrowserBase):
    def visit_console(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

    def visit_console_unauthenticated(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")
