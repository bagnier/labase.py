from tests.e2e.drivers.protocols import ApiProtocol


class ConsoleApiMixin(ApiProtocol):
    def visit_console(self) -> None:
        self._response = self._run(self._c.get("/console"))

    def visit_console_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/console"))
