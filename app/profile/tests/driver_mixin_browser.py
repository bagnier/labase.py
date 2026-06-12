from tests.e2e.drivers.protocols import BrowserProtocol


class ProfileBrowserMixin(BrowserProtocol):
    def _profile_url(self) -> str:
        return f"{self._base_url}/profile"

    def view_profile(self) -> None:
        self._last_response = self._p.goto(self._profile_url(), wait_until="networkidle")

    def update_display_name(self, name: str) -> None:
        self._p.goto(self._profile_url(), wait_until="networkidle")
        self._p.fill("input[name=display_name]", name)
        with self._p.expect_response(
            lambda r: "/profile" in r.url and r.request.method == "POST", timeout=10000
        ) as resp_info:
            self._p.click("button[type=submit]")
        self._last_response = resp_info.value

    def assert_display_name(self, name: str | None) -> None:
        self._p.goto(self._profile_url(), wait_until="networkidle")
        value = self._p.locator("input[name=display_name]").input_value()
        if name:
            assert value == name, f"Expected display name '{name}', got '{value}'"
        else:
            assert value == "", f"Expected empty display name, got '{value}'"

    def assert_last_update_rejected(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 422, f"Expected 422, got {self._last_response.status}"

    def assert_email_read_only(self) -> None:
        self._p.goto(self._profile_url(), wait_until="networkidle")
        disabled = self._p.locator("input[disabled]")
        assert disabled.count() >= 1, "Expected at least one disabled input on profile page"
