from tests.e2e.drivers.protocols import ApiProtocol


class DashboardApiMixin(ApiProtocol):
    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def assert_link_to_todos(self) -> None:
        assert self._response is not None
        slug = getattr(self, "_active_org_slug", "")
        expected = f"/{slug}/todos"
        assert expected in self._response.text, f"No link to {expected!r} found on dashboard"

    def view_profile(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def assert_link_to_org_dashboard(self) -> None:
        assert self._response is not None
        slug = getattr(self, "_active_org_slug", "")
        expected = f"/{slug}/dashboard"
        assert expected in self._response.text, f"No link to {expected!r} found on profile"

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "_active_org_slug", "")
        self._response = self._run(self._c.get(f"/{slug}/dashboard"))

    def assert_org_dashboard_visible(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, (
            f"Expected 200 for org dashboard, got {self._response.status_code}"
        )

    def visit_console(self) -> None:
        self._response = self._run(self._c.get("/console"))

    def visit_profile_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def visit_org_dashboard_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/any-org/dashboard"))

    def visit_console_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/console"))
