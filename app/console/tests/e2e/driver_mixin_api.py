import httpx

from tests.e2e.drivers.api_base import ApiBase


class ConsoleApiMixin(ApiBase):
    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        super().reset_session()

    def visit_console(self) -> None:
        self.response = self.client().get("/console")

    def visit_console_unauthenticated(self) -> None:
        self.response = self.client().get("/console")
