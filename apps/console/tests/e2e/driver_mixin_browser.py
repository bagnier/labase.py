from playwright.sync_api import Page, Response, expect

from apps.auth.tests.given_helpers import (
    clear_all_admin_roles,
    create_user,
    delete_user_if_exists,
    set_admin_role,
)
from apps.shared.events.listener import EventListener
from tests.e2e.drivers.browser_base import BrowserBase

_ADMIN_PASSWORD = "Test1234!"
_USER_PASSWORD = "Secret1!"


class ConsoleBrowserMixin(BrowserBase):
    def sign_in_as_admin(self, email: str) -> None:
        # Role set before login, so the JWT carries it; the admin gets its own context.
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))
        self._admin_email = email
        self._admin_acting = email
        if email in self._contexts:
            self._contexts.pop(email).close()
            self._pages.pop(email, None)
        ctx = self._browser.new_context()
        self._contexts[email] = ctx
        setup_page = ctx.new_page()
        setup_page.goto(f"{self.base_url}/auth/login")
        setup_page.get_by_label("Email").fill(email)
        setup_page.get_by_label("Password").fill(_ADMIN_PASSWORD)
        setup_page.get_by_role("button", name="Sign in").click()
        setup_page.wait_for_url("**/profile", timeout=10000)
        self._pages[email] = setup_page
        self.set_acting_email(email)

    def _as_admin(self) -> None:
        assert self._admin_acting is not None
        self.set_acting_email(self._admin_acting)

    def _open_console(self, page: Page | None = None) -> Response | None:
        """Through the top bar's console button."""
        target = page if page is not None else self.page
        with target.expect_navigation(wait_until="load") as nav:
            target.locator("a[href='/console']").first.click()
        return nav.value

    def visit_console(self) -> None:
        self._as_admin()
        self.last_response = self._open_console()

    def visit_console_unauthenticated(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

    def try_open_console(self) -> None:
        """Acts as the current (non-admin) user's page — no admin re-targeting."""
        self.last_response = self.page.goto(f"{self.base_url}/console", wait_until="load")

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
    def open_console_link(self, href: str) -> Response | None:
        """Console, then its link to ``href``."""
        self._as_admin()
        self._open_console()
        with self.page.expect_navigation(wait_until="load") as nav:
            self.page.locator(f"a[href='{href}']").first.click()
        return nav.value

    def open_console_settings(self, app: str) -> None:
        self.open_console_link(f"/console/{app}")

    def _on_console_settings(self, app: str, *, fresh: bool = False) -> None:
        """On an app's settings screen; ``fresh`` reloads it to read what the server saved."""
        self._as_admin()
        self.be_on(f"/console/{app}", lambda: self.open_console_settings(app), fresh=fresh)

    def _setting_locator(self, key: str):
        return self.page.locator(f"[data-setting-key='{key}']")

    def _field(self, row, key: str):
        # The setting key is the field's accessible name.
        return row.get_by_label(key)

    def set_org_override(self, app: str, key: str, value: str) -> None:
        self._on_console_settings(app)
        handle = getattr(self, "active_org_handle", "")
        self.page.get_by_label("Organisation handle").fill(handle)
        self.page.get_by_label("Setting key").select_option(key)
        # Only the selected key's widget is enabled.
        self.page.get_by_label(f"Override value for {key}").fill(value)

        def posted(r):
            return "/org-settings" in r.url and r.request.method == "POST"

        with self.page.expect_response(posted):
            self.page.get_by_role("button", name="Override").click()

    def assert_org_override_listed(self, app: str, key: str, value: str) -> None:
        handle = getattr(self, "active_org_handle", "")
        selector = f"[data-org-override='{handle}:{key}']"
        self.page.wait_for_selector(selector, timeout=5000)
        row_text = self.page.locator(selector).inner_text()
        assert value in row_text, f"expected {value!r} in override row: {row_text!r}"

    def set_console_setting(self, app: str, key: str, value: str) -> None:
        # Fields save on change.
        self._on_console_settings(app)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, key)

        def posted(r):
            return "/settings/" in r.url and r.request.method == "PUT"

        with self.page.expect_response(posted):
            if kind == "boolean":
                # sr-only behind a styled track: forced.
                if (value == "true") != field.is_checked():
                    field.click(force=True)
                else:
                    field.dispatch_event("change")
            elif field.evaluate("el => el.tagName") == "SELECT":
                field.select_option(value)
            else:
                # Text saves on blur.
                field.fill(value)
                field.blur()
        self.drive_spread()

    def drive_spread(self) -> None:
        """One listener tick now, rather than racing the server's own."""
        if self._server is None:
            return
        self._server.run(EventListener(0).tick())

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
        self._on_console_settings(app, fresh=True)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, key)
        if kind == "boolean":
            actual = "true" if field.is_checked() else "false"
        else:
            actual = field.input_value()
        assert actual == value, f"setting {key!r}: expected {value!r}, got {actual!r}"

    def assert_console_supabase_link(self, app: str, fragment: str) -> None:
        self._on_console_settings(app)
        link = self.page.locator(f"[data-supabase-app='{app}']")
        href = link.get_attribute("href")
        assert href is not None, f"no Supabase link for {app!r}"
        assert fragment in href, f"{fragment!r} not in {href!r}"

    # ── server admins ────────────────────────────────────────────────────────────
    def ensure_no_server_admin(self) -> None:
        clear_all_admin_roles()

    def seed_existing_admin(self) -> None:
        # An admin exists, so the bootstrap promotes nobody; seeded in GoTrue directly.
        email = "seed-admin@example.com"
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))

    def register_and_sign_in(self, email: str) -> None:
        self.context_for(email)
        self.set_acting_email(email)

    def register_regular_user(self, email: str) -> None:
        self.context_for(email)

    def _login(self, email: str) -> None:
        # Signed in, /auth/login would redirect away.
        self.context_for(email).clear_cookies()
        page = self.page_for(email)
        page.goto(f"{self.base_url}/auth/login")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_USER_PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/profile", timeout=10000)

    def sign_in_again(self, email: str) -> None:
        # A fresh token carries the new role.
        self._login(email)
        self.set_acting_email(email)

    def assert_can_open_console(self, email: str) -> None:
        page = self.page_for(email)
        expect(page.locator("a[href='/console']").first).to_be_visible()
        resp = self._open_console(page)
        assert resp is not None, "Expected 200, got no response"
        assert resp.status == 200, f"Expected 200, got {resp.status}"

    def assert_refused_console(self, email: str) -> None:
        """No button, and the server refuses the request anyway."""
        page = self.page_for(email)
        expect(page.locator("a[href='/console']")).to_have_count(0)
        resp = page.request.fetch(f"{self.base_url}/console", method="GET")
        assert resp.status == 404, f"Expected 404, got {resp.status}"

    def _walk_to_admins(self) -> None:
        """Console → Users tile → “Manage admins”."""
        self.open_console_settings("users")
        with self.page.expect_navigation(wait_until="load"):
            self.page.locator("a[href='/console/admins']").first.click()

    def _goto_admins(self, *, fresh: bool = False) -> Page:
        """On the admins screen; ``fresh`` reloads it from the server."""
        self._as_admin()
        self.be_on("/console/admins", self._walk_to_admins, fresh=fresh)
        return self.page

    def open_admins_page(self) -> None:
        self._goto_admins()

    def assert_admin_list_status(self, email: str, *, is_admin: bool) -> None:
        page = self._goto_admins(fresh=True)
        row = page.query_selector(f"[data-admin-email='{email}']")
        assert row is not None, f"{email!r} not found on admins page"
        actual = row.get_attribute("data-admin-status")
        expected = "admin" if is_admin else "regular"
        assert actual == expected, f"{email!r}: expected {expected!r}, got {actual!r}"

    def assert_email_absent_from_admin_list(self, email: str) -> None:
        page = self._goto_admins(fresh=True)
        row = page.query_selector(f"[data-admin-email='{email}']")
        assert row is None, f"{email!r} unexpectedly on admins page"

    def add_server_admin_by_email(self, email: str) -> None:
        page = self._goto_admins()
        self.last_response = self.submit_labelled_form(
            page,
            {"Admin email": email},
            page.get_by_role("button", name="Add admin"),
            method="POST",
            path_token="/console/admins",
        )

    def assert_admin_add_error(self, email: str) -> None:
        el = self.page.query_selector(f"[data-admin-add-error='{email}']")
        assert el is not None, f"no add-error shown for {email!r}"

    def designate_server_admin(self, email: str) -> None:
        # Through the add-by-email form.
        self.add_server_admin_by_email(email)
        self.page.locator(f"[data-admin-email='{email}']").wait_for(state="attached")

    def revoke_server_admin(self, email: str) -> None:
        # The button is disabled for the last admin: the request is sent directly.
        self._as_admin()
        self.last_response = self.context.request.put(
            f"{self.base_url}/console/admins/{email}", form={"is_admin": "false"}
        )

    def try_designate_server_admin(self, email: str) -> None:
        resp = self.context.request.put(
            f"{self.base_url}/console/admins/{email}", form={"is_admin": "true"}
        )
        self._denied_status = resp.status
