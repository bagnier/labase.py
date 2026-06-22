from app.auth.tests.given_helpers import (
    create_user,
    delete_user_if_exists,
    set_admin_role,
)
from tests.e2e.drivers.browser_base import BrowserBase

_ADMIN_PASSWORD = "Test1234!"


class ConsoleBrowserMixin(BrowserBase):
    def sign_in_as_admin(self, email: str) -> None:
        # Admin role must be set *before* login so the issued JWT carries app_metadata.role.
        # Create + promote out of band (admin API), then log in on the current (visitor) context —
        # not context_for(), which auto-logs-in at creation with the wrong password / no role.
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))
        self._admin_email = email
        self._admin_acting = self._acting_email  # the context that will hold the admin session
        page = self.page
        page.goto(f"{self.base_url}/auth/login")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", _ADMIN_PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url("**/profile", timeout=10000)

    def _as_admin(self) -> None:
        # Multi-user scenarios sign in other users (own contexts) after the admin; switch back
        # to the context that holds the admin session.
        assert self._admin_acting is not None
        self.set_acting_email(self._admin_acting)

    def visit_console(self) -> None:
        self._as_admin()
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

    def visit_console_unauthenticated(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

    def try_open_console(self) -> None:
        # Acts as the current (non-admin) user's page — no admin re-targeting.
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

    def assert_console_not_found(self) -> None:
        status = getattr(self, "_denied_status", None)
        if status is None:
            assert self.last_response is not None
            status = self.last_response.status
        assert status == 404, f"Expected 404, got {status}"

    def reset_session(self) -> None:
        self._denied_status = None
        self._admin_email = None
        self._admin_acting = None
        super().reset_session()

    # ── overviews ──────────────────────────────────────────────────────────────
    def assert_console_overview_visible(self, key: str) -> None:
        self.page.wait_for_selector(f"[data-overview-key='{key}']", timeout=5000)

    def assert_console_overview_shows(self, key: str, text: str) -> None:
        card = self.page.locator(f"[data-overview-key='{key}']")
        assert text in card.inner_text(), f"{text!r} not in {key!r} overview"

    # ── settings ───────────────────────────────────────────────────────────────
    def open_console_settings(self, app: str) -> None:
        self._as_admin()
        self.page.goto(f"{self.base_url}/console/{app}", wait_until="load")

    def _setting_locator(self, key: str):
        return self.page.locator(f"[data-setting-key='{key}']")

    def _field(self, row, kind: str | None):
        # Boolean rows carry a hidden + a checkbox both named "value"; target the checkbox.
        if kind == "boolean":
            return row.locator("input[type='checkbox']")
        return row.locator("input[name='value']")

    def set_console_setting(self, app: str, key: str, value: str) -> None:
        self.open_console_settings(app)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, kind)
        if kind == "boolean":
            if (value == "true") != field.is_checked():
                field.click()
        else:
            field.fill(value)

        def posted(r):
            return "/settings/" in r.url and r.request.method == "PUT"

        with self.page.expect_response(posted):
            row.locator("button[type='submit']").click()

    def try_set_console_setting(self, app: str, key: str, value: str) -> None:
        self._denied_status = self.page.evaluate(
            """async ({app, key, value}) => {
                const r = await fetch(`/console/${app}/settings/${key}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({value}),
                });
                return r.status;
            }""",
            {"app": app, "key": key, "value": value},
        )

    def assert_console_setting_shown(self, app: str, key: str, value: str) -> None:
        self.open_console_settings(app)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, kind)
        if kind == "boolean":
            actual = "true" if field.is_checked() else "false"
        else:
            actual = field.input_value()
        assert actual == value, f"setting {key!r}: expected {value!r}, got {actual!r}"
