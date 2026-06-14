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

    def assert_profile_link_in_footer(self) -> None:
        assert self._response is not None
        html = self._response.text
        footer_start = html.find("<!-- User footer -->")
        assert footer_start != -1, "User footer comment not found in HTML"
        footer_section = html[footer_start : footer_start + 500]
        assert 'href="/profile"' in footer_section, "No /profile link found in user footer"

    def assert_no_profile_nav_link(self) -> None:
        assert self._response is not None
        html = self._response.text
        nav_start = html.find("<nav ")
        nav_end = html.find("</nav>", nav_start)
        assert nav_start != -1, "<nav> not found in HTML"
        nav_section = html[nav_start:nav_end]
        assert 'href="/profile"' not in nav_section, "Unexpected /profile link found inside <nav>"
