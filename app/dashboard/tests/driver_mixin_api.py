from tests.e2e.drivers.protocols import ApiProtocol


class DashboardApiMixin(ApiProtocol):
    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/dashboard"))

    def assert_link_to_todos(self) -> None:
        assert self._response is not None
        assert "/todos" in self._response.text, "No link to /todos found on dashboard"
