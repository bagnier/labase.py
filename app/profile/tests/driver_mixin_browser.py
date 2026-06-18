from tests.e2e.drivers.browser_base import BrowserBase


class ProfileBrowserMixin(BrowserBase):
    def _profile_url(self) -> str:
        return f"{self._base_url}/profile"

    def view_profile(self) -> None:
        self._last_response = self._p.goto(self._profile_url(), wait_until="load")

    def update_handle(self, name: str) -> None:
        self._p.goto(self._profile_url(), wait_until="load")
        self._p.fill("input[name=handle]", name)
        with self._p.expect_response(
            lambda r: "/profile" in r.url and r.request.method == "POST"
        ) as resp_info:
            self._p.click("form:has(input[name=handle]) button[type=submit]")
        self._last_response = resp_info.value

    def assert_handle(self, name: str | None) -> None:
        self._p.goto(self._profile_url(), wait_until="load")
        value = self._p.locator("input[name=handle]").input_value()
        if name:
            assert value == name, f"Expected handle '{name}', got '{value}'"
        else:
            assert value == "", f"Expected empty handle, got '{value}'"

    def assert_last_update_rejected(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status in (422, 409), (
            f"Expected 422/409, got {self._last_response.status}"
        )

    def assert_email_read_only(self) -> None:
        self._p.goto(self._profile_url(), wait_until="load")
        disabled = self._p.locator("input[disabled]")
        assert disabled.count() >= 1, "Expected at least one disabled input on profile page"

    def visit_profile_unauthenticated(self) -> None:
        self._last_response = self._p.goto(self._profile_url(), wait_until="load")

    def assert_link_to_org_dashboard(self) -> None:
        assert self._p.query_selector("a[href*='/dashboard']") is not None, (
            "No link to org dashboard found on profile"
        )

    def view_dashboard(self) -> None:
        self._last_response = self._p.goto(self._profile_url(), wait_until="load")

    def assert_link_to_todos(self) -> None:
        assert self._p.query_selector("a[href*='/todos']") is not None, (
            "No link to /todos found on dashboard"
        )

    def assert_profile_link_in_footer(self) -> None:
        link = self._p.query_selector("aside a[href='/profile']")
        assert link is not None, "No /profile link found in sidebar footer"

    def assert_no_profile_nav_link(self) -> None:
        link = self._p.query_selector("nav a[href='/profile']")
        assert link is None, "Unexpected /profile link found inside <nav>"
