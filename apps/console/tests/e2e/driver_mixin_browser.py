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
        # Admin role must be set *before* login so the issued JWT carries app_metadata.role.
        # Use an isolated browser context for the admin so the current acting user's session
        # is never polluted.
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))
        self._admin_email = email
        self._admin_acting = email  # admin lives in their own isolated context
        # Tear down any stale context from a previous call with this email
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
        setup_page.close()
        self.set_acting_email(email)

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

    def _field(self, row, key: str):
        # Boolean + text settings expose the setting key as their accessible name
        # (aria-label). Boolean rows also carry a hidden mirror named "value"; the
        # accessible name resolves unambiguously to the visible checkbox/switch.
        return row.get_by_label(key)

    def set_org_override(self, app: str, key: str, value: str) -> None:
        self.open_console_settings(app)
        handle = getattr(self, "active_org_handle", "")
        self.page.get_by_label("Organisation handle").fill(handle)
        self.page.get_by_label("Setting key").select_option(key)
        # One value widget per setting shares the "Override value for …" label; target the
        # selected key's (the only enabled one) so the locator isn't ambiguous.
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
        # Settings auto-save: changing a field fires hx-trigger="change" — no Save button.
        self.open_console_settings(app)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, key)

        def posted(r):
            return "/settings/" in r.url and r.request.method == "PUT"

        with self.page.expect_response(posted):
            if kind == "boolean":
                # Toggling the checkbox emits change directly. The input is
                # sr-only behind a styled track, so force past actionability.
                if (value == "true") != field.is_checked():
                    field.click(force=True)
                else:
                    field.dispatch_event("change")
            elif field.evaluate("el => el.tagName") == "SELECT":
                # A constrained string setting (e.g. the log level) is a <select>: pick the
                # option, which emits change directly — no blur needed.
                field.select_option(value)
            else:
                # Text/number save on blur — fill then move focus to emit change.
                field.fill(value)
                field.blur()
        self.drive_spread()

    def drive_spread(self) -> None:
        """Apply the settings change deterministically. The in-process server runs a real event
        listener that a NOTIFY would wake, but driving one tick here removes the race between the
        persist and the next assertion."""
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
        self.open_console_settings(app)
        row = self._setting_locator(key)
        kind = row.get_attribute("data-setting-type")
        field = self._field(row, key)
        if kind == "boolean":
            actual = "true" if field.is_checked() else "false"
        else:
            actual = field.input_value()
        assert actual == value, f"setting {key!r}: expected {value!r}, got {actual!r}"

    def assert_console_supabase_link(self, app: str, fragment: str) -> None:
        self.open_console_settings(app)
        link = self.page.locator(f"[data-supabase-app='{app}']")
        href = link.get_attribute("href")
        assert href is not None, f"no Supabase link for {app!r}"
        assert fragment in href, f"{fragment!r} not in {href!r}"

    # ── server admins ────────────────────────────────────────────────────────────
    def ensure_no_server_admin(self) -> None:
        clear_all_admin_roles()

    def seed_existing_admin(self) -> None:
        # An admin must exist so a later registrant is *not* auto-promoted by the bootstrap.
        # Seeded straight into GoTrue (no browser context) to leave the acting user untouched.
        email = "seed-admin@example.com"
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))

    def register_and_sign_in(self, email: str) -> None:
        # context_for registers (firing the bootstrap) then logs in — the issued token
        # already carries the admin claim where the user was promoted.
        self.context_for(email)
        self.set_acting_email(email)

    def register_regular_user(self, email: str) -> None:
        self.context_for(email)

    def _login(self, email: str) -> None:
        # Drop the stale session first; otherwise /auth/login redirects to /profile (already
        # signed in) and the email field is disabled.
        self.context_for(email).clear_cookies()
        page = self.page_for(email)
        page.goto(f"{self.base_url}/auth/login")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_USER_PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_url("**/profile", timeout=10000)

    def sign_in_again(self, email: str) -> None:
        # Refresh the cookie so the freshly-granted admin claim lands in the token.
        self._login(email)
        self.set_acting_email(email)

    def assert_can_open_console(self, email: str) -> None:
        resp = self.page_for(email).goto(f"{self.base_url}/console", wait_until="load")
        assert resp is not None, "Expected 200, got no response"
        assert resp.status == 200, f"Expected 200, got {resp.status}"

    def assert_refused_console(self, email: str) -> None:
        resp = self.page_for(email).goto(f"{self.base_url}/console", wait_until="load")
        assert resp is not None, "Expected 404, got no response"
        assert resp.status == 404, f"Expected 404, got {resp.status}"

    def _goto_admins(self):
        self._as_admin()
        page = self.page
        page.goto(f"{self.base_url}/console/admins", wait_until="load")
        return page

    def open_admins_page(self) -> None:
        self._goto_admins()

    def assert_admin_list_status(self, email: str, *, is_admin: bool) -> None:
        page = self._goto_admins()
        row = page.query_selector(f"[data-admin-email='{email}']")
        assert row is not None, f"{email!r} not found on admins page"
        actual = row.get_attribute("data-admin-status")
        expected = "admin" if is_admin else "regular"
        assert actual == expected, f"{email!r}: expected {expected!r}, got {actual!r}"

    def assert_email_absent_from_admin_list(self, email: str) -> None:
        page = self._goto_admins()
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
        # Designation now flows through the add-by-email form (regular users aren't listed).
        self.add_server_admin_by_email(email)
        self.page.locator(f"[data-admin-email='{email}']").wait_for(state="attached")

    def revoke_server_admin(self, email: str) -> None:
        # Force the request server-side: the UI disables the button for the last admin, so a
        # click can't be issued — require the server itself to enforce the guard.
        self._as_admin()
        self.last_response = self.context.request.put(
            f"{self.base_url}/console/admins/{email}", form={"is_admin": "false"}
        )

    def try_designate_server_admin(self, email: str) -> None:
        # Acts as the current (non-admin) user's context — no admin re-targeting.
        resp = self.context.request.put(
            f"{self.base_url}/console/admins/{email}", form={"is_admin": "true"}
        )
        self._denied_status = resp.status
