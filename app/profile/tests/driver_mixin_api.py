from tests.e2e.drivers.protocols import ApiProtocol


class ProfileApiMixin(ApiProtocol):
    def view_profile(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def update_display_name(self, name: str) -> None:
        self._response = self._run(self._c.post("/profile", data={"display_name": name}))

    def assert_display_name(self, name: str | None) -> None:
        resp = self._run(self._c.get("/profile"))
        assert resp.status_code == 200, f"GET /profile returned {resp.status_code}"
        html = resp.text
        if name:
            assert name in html, f"Expected display name '{name}' in profile page HTML"

    def assert_last_update_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 422, f"Expected 422, got {self._response.status_code}"

    def assert_email_read_only(self) -> None:
        resp = self._run(self._c.get("/profile"))
        html = resp.text
        assert "disabled" in html, "Expected a disabled input field on the profile page"

    def visit_profile_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def assert_link_to_org_dashboard(self) -> None:
        assert self._response is not None
        slug = getattr(self, "_active_org_slug", "")
        expected = f"/{slug}/dashboard"
        assert expected in self._response.text, f"No link to {expected!r} found on profile"

    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/profile"))

    def assert_link_to_todos(self) -> None:
        assert self._response is not None
        slug = getattr(self, "_active_org_slug", "")
        expected = f"/{slug}/todos"
        assert expected in self._response.text, f"No link to {expected!r} found on dashboard"
