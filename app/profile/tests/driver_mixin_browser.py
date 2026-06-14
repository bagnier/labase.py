from tests.e2e.drivers.protocols import BrowserProtocol


class ProfileBrowserMixin(BrowserProtocol):
    def _profile_url(self) -> str:
        return f"{self._base_url}/profile"

    def view_profile(self) -> None:
        self._last_response = self._p.goto(self._profile_url(), wait_until="load")

    def update_display_name(self, name: str) -> None:
        assert self._context
        self._last_response = self._context.request.post(
            self._profile_url(),
            form={"display_name": name},
        )

    def assert_display_name(self, name: str | None) -> None:
        self._p.goto(self._profile_url(), wait_until="load")
        value = self._p.locator("input[name=display_name]").input_value()
        if name:
            assert value == name, f"Expected display name '{name}', got '{value}'"
        else:
            assert value == "", f"Expected empty display name, got '{value}'"

    def assert_last_update_rejected(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 422, f"Expected 422, got {self._last_response.status}"

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
