from tests.e2e.drivers.protocols import ApiProtocol


class DashboardApiMixin(ApiProtocol):
    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/dashboard"))

    def assert_link_to_todos(self) -> None:
        assert self._response is not None
        slug = getattr(self, "_active_org_slug", "")
        expected = f"/orgs/{slug}/todos"
        assert expected in self._response.text, f"No link to {expected!r} found on dashboard"
