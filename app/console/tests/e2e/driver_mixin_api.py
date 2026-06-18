from tests.e2e.drivers.api_base import ApiBase


class ConsoleApiMixin(ApiBase):
    def visit_console(self) -> None:
        self._response = self.run(self.client.get("/console"))

    def visit_console_unauthenticated(self) -> None:
        self._response = self.run(self.client.get("/console"))
