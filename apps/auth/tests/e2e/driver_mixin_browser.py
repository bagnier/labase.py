from datetime import UTC, datetime
from uuid import uuid4

from apps.auth.tests.given_helpers import (
    create_unconfirmed_user,
    delete_user_if_exists,
    find_users,
)
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.browser_base import VISITOR, BrowserBase


class AuthBrowserMixin(BrowserBase):
    last_registered_email: str | None

    def reset_session(self) -> None:
        self.last_registered_email = None
        self._reset_email: str | None = None
        self._reset_requested_at: datetime | None = None
        self._confirmation_requested_at: datetime | None = None
        self._totp_secret: str | None = None
        super().reset_session()

    def _delete_user_if_exists(self, email: str) -> None:
        delete_user_if_exists(email)

    # ── HTML page access (auth smoke flows) ────────────────────────────────────
    def visit(self, path: str) -> None:
        self.last_response = self.page.goto(f"{self.base_url}{path}", wait_until="load")

    # The front door: a visitor arriving at sign-in or registration is the entry point the base
    # blesses, not a deep link — and it is a `when`, so the assertions that follow read the page
    # it opened rather than fetching one of their own.
    def start_to_sign_in(self) -> None:
        self.page_for(VISITOR).goto(f"{self.base_url}/auth/login", wait_until="load")

    def start_to_register(self) -> None:
        self.page_for(VISITOR).goto(f"{self.base_url}/auth/register", wait_until="load")

    def assert_visitor_page_offers(self, contains: str) -> None:
        content = self.page_for(VISITOR).content()
        assert contains in content, f"'{contains}' not on the page the visitor opened"

    def assert_page_loaded(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 200, f"Expected 200, got {self.last_response.status}"

    def sign_in(self, email: str, password: str) -> None:
        self.page.goto(f"{self.base_url}/auth/login")
        if "/auth/login" not in self.page.url:
            # The acting context is already signed in (login redirects away):
            # "a visitor signs in" happens on a fresh visitor context instead.
            self.clear_acting_email()
            self.page.goto(f"{self.base_url}/auth/login")
        resp = self.submit_labelled_form(
            self.page,
            {"Email": email, "Password": password},
            self.page.get_by_role("button", name="Sign in"),
            method="POST",
            path_token="/auth/login",
        )
        assert resp is not None
        self.last_response = resp
        if resp.status == 303 or resp.headers.get("hx-redirect"):
            self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)
            self.adopt_current_context(email)
            # Same as the api driver does on sign-in: whoever just authenticated brings their own
            # org, and a stale handle from the previous actor would send every later step to it.
            self._store_active_org_handle()
        else:
            self.page.wait_for_load_state("domcontentloaded")

    def ensure_registered(self, email: str, password: str) -> None:
        page = self.page.context.new_page()
        page.goto(f"{self.base_url}/auth/register")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Create my account").click()
        page.wait_for_load_state("domcontentloaded")
        page.close()
        self.drain_task_queue()  # run UserCreated's reactions (personal org, admin bootstrap) now

    def register(self, email: str, password: str) -> None:
        self.last_registered_email = email
        self.page.goto(f"{self.base_url}/auth/register")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Email": email, "Password": password},
            self.page.get_by_role("button", name="Create my account"),
            method="POST",
            path_token="/auth/register",
        )
        self.page.wait_for_load_state("domcontentloaded")
        self.drain_task_queue()  # run UserCreated's reactions (personal org, admin bootstrap) now

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def _store_active_org_handle(self) -> None:
        """Read the handle off the org card link — the caller leaves the page on /profile.

        Not every signed-in user has one: an account whose personal org does not exist yet renders
        the organisations panel with no card in it. So anchor on the panel's own create form —
        same server-rendered response as the cards, present either way — and read the cards only
        once it is attached. Absence is then a settled fact rather than a race, which is what a
        bounded timeout here could never tell apart: it would leave the previous actor's handle in
        place and send the rest of the scenario to the wrong organisation, silently.
        """
        self.page.get_by_label("Organisation name").wait_for(state="attached")
        link = self.page.locator("[data-organisation-card] a[href*='/dashboard']").first
        if link.count() == 0:
            return
        handle = (link.get_attribute("href") or "").strip("/").split("/")[0]
        if handle:
            self.active_org_handle = handle

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_org_handle()

    def logout_action(self) -> None:
        # Sign out the way a human does — no fetch(): from the profile's Account tab, submit
        # the Sign out form. If the session is already gone, the page holds no account link, or
        # following it bounces to the sign-in page: either way there is nothing left to click.
        if self.page.locator("aside a[href='/profile']").count() == 0:
            return
        self.follow_to_profile()
        if "/auth/login" in self.page.url:
            return
        self.page.get_by_role("tab", name="Account", exact=True).check()
        self.page.get_by_role("button", name="Sign out").click()
        self.page.wait_for_load_state("load")

    def request_password_reset(self, email: str) -> None:
        self._reset_email = email
        self._reset_requested_at = datetime.now(UTC)
        self.page.goto(f"{self.base_url}/auth/login", wait_until="load")
        self.page.get_by_role("link", name="Forgot password?").click()
        self.page.wait_for_url(f"{self.base_url}/auth/forgot-password", timeout=5000)
        self.page.get_by_label("Email").fill(email)
        self.page.get_by_role("button", name="Send reset link").click()
        self.page.wait_for_selector(".alert", timeout=5000)

    def reset_password_via_email(self, new_password: str) -> None:
        assert self._reset_email, "no reset requested"
        assert self._reset_requested_at, "no reset requested"
        # The recovery mail is really fetched from the catcher; the link targets the
        # dev SITE_URL, so we carry its token to this driver's own server port.
        token_hash = mailbox.recovery_token(self._reset_email, since=self._reset_requested_at)
        self.page.goto(
            f"{self.base_url}/auth/reset-password?token_hash={token_hash}&type=recovery",
            wait_until="load",
        )
        self.page.get_by_label("New password").fill(new_password)
        self.page.get_by_role("button", name="Set new password").click()
        self.page.wait_for_url(f"{self.base_url}/auth/login*", timeout=5000)

    def _open_profile_auth_tab(self) -> None:
        """Password/2FA/passkeys live in the profile page's "Authentication" tab
        (client-side daisyUI tabs); check its radio so the panel is visible."""
        self.page.get_by_role("tab", name="Authentication", exact=True).check()

    def change_password(self, current_password: str, new_password: str) -> None:
        self.reach_profile()
        self._open_profile_auth_tab()
        self.page.get_by_label("Current password").fill(current_password)
        self.page.get_by_label("New password").fill(new_password)
        self.page.get_by_role("button", name="Change password").click()
        self.page.wait_for_selector(".alert-success", timeout=5000)

    def assert_redirected_to_login(self) -> None:
        assert "/auth/login" in self.page.url, (
            f"Expected redirect to /auth/login, got {self.page.url}"
        )

    def assert_login_rejected(self) -> None:
        # HTMX 2.x drops 4xx responses without swapping — verify by checking
        # we were not redirected to the dashboard (i.e., sign-in was refused)
        assert "/profile" not in self.page.url, (
            f"Expected sign-in to fail but ended up at {self.page.url}"
        )

    # ── unconfirmed email ──────────────────────────────────────────────────────
    def register_unconfirmed(self, email: str, password: str) -> None:
        delete_user_if_exists(email)
        create_unconfirmed_user(email, password)

    def assert_login_rejected_with(self, message: str) -> None:
        self.assert_login_rejected()
        alert = self.page.locator(".alert", has_text=message)
        alert.wait_for(timeout=5000)

    def resend_confirmation_to(self, email: str) -> None:
        # The button sits in the failed sign-in's error state, email carried along.
        self._confirmation_requested_at = datetime.now(UTC)
        form = self.page.locator("[data-resend-confirmation]")
        assert form.locator("input[name=email]").get_attribute("value") == email
        form.get_by_role("button", name="Resend confirmation email").click()
        self.page.wait_for_load_state("load")

    def assert_confirmation_delivered(self, email: str) -> None:
        assert self._confirmation_requested_at is not None, "no resend requested"
        mailbox.wait_for_message(
            to=email, containing="token_hash=", since=self._confirmation_requested_at
        )

    def confirm_address_via_link(self, email: str) -> None:
        # The mail is really fetched from the catcher; following its link is the
        # one legitimate goto (a user clicks it from their mailbox).
        assert self._confirmation_requested_at is not None, "no resend requested"
        token_hash = mailbox.token_hash_from_mail(email, since=self._confirmation_requested_at)
        self.page.goto(
            f"{self.base_url}/auth/confirm?token_hash={token_hash}&type=signup",
            wait_until="load",
        )

    def assert_resend_offered(self) -> None:
        self.page.wait_for_selector("[data-resend-confirmation]", timeout=5000)

    def assert_resend_not_offered(self) -> None:
        assert self.page.locator("[data-resend-confirmation]").count() == 0, (
            "resend affordance should be hidden when the option is off"
        )

    # ── two-factor (TOTP) ─────────────────────────────────────────────────────
    def enroll_totp(self) -> None:
        import pyotp

        self.reach_profile()
        self._open_profile_auth_tab()
        self.page.locator("[data-twofa]").get_by_role("button", name="Enable two-factor").click()
        self.page.wait_for_selector("[data-totp-secret]", timeout=5000)
        self._totp_secret = self.page.locator("[data-totp-secret]").get_attribute(
            "data-totp-secret"
        )
        assert self._totp_secret, "no TOTP secret rendered"
        section = self.page.locator("[data-twofa]")
        section.get_by_label("Authenticator code").fill(pyotp.TOTP(self._totp_secret).now())
        section.get_by_role("button", name="Confirm", exact=True).click()
        self.page.wait_for_selector("[data-twofa-active]", timeout=5000)

    def assert_twofa_enabled(self) -> None:
        self._open_profile_auth_tab()
        self.page.wait_for_selector("[data-twofa-active]", timeout=5000)

    def assert_mfa_challenge(self) -> None:
        self.page.wait_for_selector("[data-mfa-form]", timeout=5000)

    def enter_totp_code(self, code: str | None) -> None:
        import pyotp

        if code is None:
            assert self._totp_secret, "no enrolled secret"
            code = pyotp.TOTP(self._totp_secret).now()
        self.page.get_by_label("Authenticator code").fill(code)
        self.page.get_by_role("button", name="Verify").click()
        self.page.wait_for_load_state("load")

    def assert_totp_rejected(self) -> None:
        alert = self.page.locator("[data-mfa-form] .alert", has_text="did not work")
        alert.wait_for(timeout=5000)

    def assert_twofa_not_offered(self, email: str) -> None:
        # Their own page, read from the server: the option was turned off after it rendered.
        self.set_acting_email(email)
        self.reach_profile(fresh=True)
        assert self.page.locator("[data-twofa]").count() == 0, (
            "two-factor section should be hidden when the option is off"
        )

    # ── OAuth social sign-in ───────────────────────────────────────────────────
    # The sign-in page is a visitor's view — the acting context may be a
    # signed-in admin (who just flipped the switch), whom /auth/login redirects.
    def _oauth_button(self, provider: str):
        return self.page_for(VISITOR).locator(f"[data-oauth-provider='{provider}']")

    def assert_oauth_offered(self, provider: str) -> None:
        self._oauth_button(provider).wait_for(timeout=5000)

    def assert_oauth_not_offered(self, provider: str) -> None:
        assert self._oauth_button(provider).count() == 0, f"unexpected {provider} button"

    def start_oauth(self, provider: str) -> None:
        """Click the provider button; the app answers 303 to GoTrue's authorize URL.

        The navigation then leaves the app (GoTrue errors without real provider
        credentials locally) — the scenario only asserts the captured hand-off.
        """
        page = self.page_for(VISITOR)
        page.goto(f"{self.base_url}/auth/login", wait_until="load")
        with page.expect_response(
            lambda r: f"/auth/oauth/{provider}" in r.url and r.request.method == "GET"
        ) as info:
            self._oauth_button(provider).click()
        self._oauth_response = info.value

    def assert_oauth_authorize_redirect(self, provider: str) -> None:
        resp = getattr(self, "_oauth_response", None)
        assert resp is not None, "start_oauth was not called"
        assert resp.status == 303, f"expected 303, got {resp.status}"
        location = resp.headers.get("location", "")
        assert "/auth/v1/authorize" in location, f"unexpected redirect: {location}"
        assert f"provider={provider}" in location, f"unexpected provider in: {location}"

    # ── Passkeys ───────────────────────────────────────────────────────────────
    # The real thing: static/js/passkeys.js drives navigator.credentials against a
    # CDP virtual authenticator, and GoTrue verifies the signed origin — possible
    # because the e2e server's origin is pinned into rp_origins (see browser_base).
    def _attach_virtual_authenticator(self, page):
        client = page.context.new_cdp_session(page)
        client.send("WebAuthn.enable")
        added = client.send(
            "WebAuthn.addVirtualAuthenticator",
            {
                "options": {
                    "protocol": "ctap2",
                    "transport": "internal",
                    "hasResidentKey": True,
                    "hasUserVerification": True,
                    "isUserVerified": True,
                    "automaticPresenceSimulation": True,
                },
            },
        )
        return client, added["authenticatorId"]

    def assert_passkey_signin_offered(self) -> None:
        self.page_for(VISITOR).locator("[data-passkey-signin]").wait_for(timeout=5000)

    def assert_passkey_signin_not_offered(self) -> None:
        assert self.page_for(VISITOR).locator("[data-passkey-signin]").count() == 0, (
            "unexpected passkey button"
        )

    def add_passkey(self) -> None:
        page = self.page
        client, authenticator_id = self._attach_virtual_authenticator(page)
        self.reach_profile()
        self._open_profile_auth_tab()
        page.locator("[data-passkey-register]").click()
        # passkeys.js reloads the page once GoTrue accepted the attestation; the
        # fresh page opens on the default tab, so re-open Authentication to see it.
        page.locator("[data-passkey-name]").first.wait_for(state="attached", timeout=10000)
        self._open_profile_auth_tab()
        page.locator("[data-passkey-name]").first.wait_for(timeout=5000)
        # Carry the credential over to the sign-in context's own authenticator.
        credentials = client.send("WebAuthn.getCredentials", {"authenticatorId": authenticator_id})[
            "credentials"
        ]
        assert credentials, "the virtual authenticator holds no credential"
        self._passkey_credential = credentials[0]

    def assert_passkey_listed(self) -> None:
        self._open_profile_auth_tab()
        self.page.locator("[data-passkey-name]").first.wait_for(timeout=5000)

    def sign_in_with_passkey(self) -> None:
        credential = getattr(self, "_passkey_credential", None)
        assert credential is not None, "add_passkey was not called"
        self.clear_acting_email()  # the visitor doing the ceremony becomes the acting context
        page = self.page_for(VISITOR)
        client, authenticator_id = self._attach_virtual_authenticator(page)
        client.send(
            "WebAuthn.addCredential",
            {"authenticatorId": authenticator_id, "credential": credential},
        )
        page.goto(f"{self.base_url}/auth/login", wait_until="load")
        page.locator("[data-passkey-signin]").click()
        # passkeys.js follows the server's redirect once the assertion verified.
        page.wait_for_url(f"{self.base_url}/profile*", timeout=10000)

    # ── user management (console accounts screen) ─────────────────────────────
    def _accounts_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def open_accounts_screen(self) -> None:
        """Console → the Users tile → its “Accounts” link, the path the console lays out."""
        open_settings = getattr(self, "open_console_settings", None)  # console mixin
        assert open_settings is not None
        open_settings("users")
        with self.page.expect_navigation(wait_until="load"):
            self.page.locator("a[href='/console/accounts']").first.click()

    def _account_row(self, email: str):
        return self.page.locator(f"[data-account='{email}']")

    def assert_account_listed(self, email: str) -> None:
        self._account_row(email).wait_for(timeout=5000)

    def assert_account_not_listed(self, email: str) -> None:
        assert self._account_row(email).count() == 0, f"{email!r} still listed"

    def filter_accounts(self, query: str) -> None:
        search = self.page.get_by_label("Filter accounts by email")
        search.click()
        # press_sequentially fires the keyup events the HTMX debounce listens for.
        search.press_sequentially(query)

    def assert_account_in_filtered_list(self, email: str) -> None:
        self._account_row(email).wait_for(timeout=5000)

    def assert_account_not_in_filtered_list(self, email: str) -> None:
        self._account_row(email).wait_for(state="detached", timeout=5000)

    def set_account_state(self, email: str, action: str) -> None:
        self.open_accounts_screen()
        button = {"disable": "Disable", "enable": "Enable", "delete": "Delete"}[action]
        self._account_row(email).get_by_role("button", name=button).click()
        self.page.wait_for_load_state("load")

    def try_open_accounts_screen(self) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("GET", "/console/accounts")

    def try_open_accounts_screen_as_admin(self) -> None:
        self._accounts_as_admin()
        self.try_open_accounts_screen()

    def assert_redirected_to_dashboard(self) -> None:
        self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)
        assert "/profile" in self.page.url, f"Expected /profile, got {self.page.url}"

    def assert_registration_successful(self) -> None:
        content = self.page.content()
        assert "Account created" in content, "'Account created' not found in registration response"
        assert self.last_registered_email is not None
        assert find_users(self.last_registered_email), (
            f"User {self.last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 400, f"Expected 400, got {self.last_response.status}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        self.page.wait_for_selector(".alert-error", timeout=3000)
        assert message in self.page.content(), (
            f"'{message}' not found in page after registration failure"
        )

    # ── impersonation ──────────────────────────────────────────────────────────

    def impersonate(self, email: str) -> None:
        goto_admins = getattr(self, "_goto_admins", None)  # console mixin
        assert goto_admins is not None
        goto_admins()
        self.page.get_by_label("Impersonate email").fill(email)
        self.page.get_by_role("button", name="View as user").click()
        self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)

    def impersonate_from_accounts(self, email: str) -> None:
        self.open_accounts_screen()
        self._account_row(email).get_by_role("button", name="View as user").click()
        self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)

    def assert_viewing_as(self, email: str) -> None:
        assert email in self.page.content(), f"{email!r} not on the impersonated page"

    def assert_impersonation_banner(self) -> None:
        self.page.wait_for_selector("[data-impersonation-banner]", timeout=5000)

    def stop_impersonating(self) -> None:
        self.page.get_by_role("button", name="Stop impersonating").click()
        self.page.wait_for_url(f"{self.base_url}/console", timeout=5000)

    def assert_back_as_admin(self, email: str) -> None:
        assert self.page.locator("[data-impersonation-banner]").count() == 0
        assert "/console" in self.page.url, f"expected the console, got {self.page.url}"

    def try_impersonate(self, email: str) -> None:
        probe = getattr(self, "_probe_blocked", None)  # organizations mixin
        assert probe is not None
        probe("POST", "/auth/impersonate", form={"email": email})

    def assert_impersonation_refused(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 404, f"Expected 404, got {self.last_response.status}"
