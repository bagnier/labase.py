from datetime import UTC, datetime
from uuid import uuid4

import httpx

from apps.auth.tests.given_helpers import (
    create_unconfirmed_user,
    delete_user_if_exists,
    find_users,
)
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.api_base import VISITOR, ApiBase
from tests.e2e.drivers.webauthn import PasskeyDevice


class AuthApiMixin(ApiBase):
    last_registered_email: str | None

    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self.last_registered_email = None
        self._reset_email: str | None = None
        self._reset_requested_at: datetime | None = None
        self._confirmation_requested_at: datetime | None = None
        self._totp_secret: str | None = None
        self._mfa_challenge: dict | None = None
        super().reset_session()

    # ── HTML page access (auth smoke flows) ────────────────────────────────────
    def visit(self, path: str) -> None:
        self.response = self.client().get(path, follow_redirects=True)

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self.client().get(path)
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_page_loaded(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 200, f"Expected 200, got {self.response.status_code}"

    def _store_active_slug(self) -> None:
        resp = self.client().get("/organizations")
        if resp.status_code == 200 and resp.json():
            self.active_org_handle = resp.json()[0]["handle"]

    def sign_in(self, email: str, password: str) -> None:
        resp = self.client().post("/auth/login", json={"email": email, "password": password})
        self.response = resp
        if self.response.status_code == 200:
            # Whoever's client just authenticated holds `email`'s cookies now —
            # re-key it under that identity (visitor or a previous user alike).
            self.adopt_current_client(email)
        self._store_active_slug()

    def ensure_registered(self, email: str, password: str) -> None:
        self.client().post("/auth/register", json={"email": email, "password": password})
        self._track_auth_email(email)
        self.drain_task_queue()  # run UserCreated's reactions (personal org, admin bootstrap) now

    def register(self, email: str, password: str) -> None:
        self.last_registered_email = email
        self.response = self.client().post(
            "/auth/register", json={"email": email, "password": password}
        )
        self._track_auth_email(email)
        self.drain_task_queue()  # run UserCreated's reactions (personal org, admin bootstrap) now

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        delete_user_if_exists(email)
        self.register(email, password)

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_slug()

    def logout_action(self) -> None:
        self.response = self.client().post("/auth/logout")
        self.clear_acting_email()

    def request_password_reset(self, email: str) -> None:
        self._reset_email = email
        self._reset_requested_at = datetime.now(UTC)
        resp = self.client().post("/auth/forgot-password", json={"email": email})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def reset_password_via_email(self, new_password: str) -> None:
        assert self._reset_email and self._reset_requested_at, "no reset requested"
        token_hash = mailbox.recovery_token(self._reset_email, since=self._reset_requested_at)
        resp = self.client().post(
            "/auth/reset-password", json={"token_hash": token_hash, "password": new_password}
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def change_password(self, current_password: str, new_password: str) -> None:
        resp = self.client().post(
            "/profile/password",
            json={"current_password": current_password, "new_password": new_password},
        )
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def assert_redirected_to_login(self) -> None:
        assert self.response is not None
        hx_redirect = self.response.headers.get("hx-redirect", "")
        is_hx = "/auth/login" in hx_redirect
        is_http = self.response.status_code in (301, 302, 303, 307, 308)
        is_401 = self.response.status_code == 401
        assert is_hx or is_http or is_401, (
            f"Expected redirect to /auth/login or 401, got status={self.response.status_code}"
            f" hx-redirect={hx_redirect!r}"
        )

    def assert_login_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 401, f"Expected 401, got {self.response.status_code}"

    # ── unconfirmed email ──────────────────────────────────────────────────────
    def register_unconfirmed(self, email: str, password: str) -> None:
        delete_user_if_exists(email)
        create_unconfirmed_user(email, password)
        self._track_auth_email(email)

    def assert_login_rejected_with(self, message: str) -> None:
        self.assert_login_rejected()
        assert self.response is not None
        detail = self.response.json().get("detail", "")
        assert message in detail, f"{message!r} not in {detail!r}"

    def resend_confirmation_to(self, email: str) -> None:
        self._confirmation_requested_at = datetime.now(UTC)
        self.response = self.client().post(
            "/auth/resend-confirmation",
            json={"email": email},
            headers={"accept": "application/json"},
        )
        assert self.response.status_code == 200, (
            f"resend: {self.response.status_code} {self.response.text}"
        )

    def assert_confirmation_delivered(self, email: str) -> None:
        assert self._confirmation_requested_at is not None, "no resend requested"
        mailbox.wait_for_message(
            to=email, containing="token_hash=", since=self._confirmation_requested_at
        )

    def confirm_address_via_link(self, email: str) -> None:
        assert self._confirmation_requested_at is not None, "no resend requested"
        token_hash = mailbox.token_hash_from_mail(email, since=self._confirmation_requested_at)
        resp = self.client().get(
            f"/auth/confirm?token_hash={token_hash}&type=signup", follow_redirects=False
        )
        assert resp.status_code == 303, f"confirm failed: {resp.status_code} {resp.text}"

    def assert_resend_offered(self) -> None:
        # REST face of the affordance: the endpoint answers (neutral 200).
        resp = self.client().post(
            "/auth/resend-confirmation",
            json={"email": ""},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}"

    def assert_resend_not_offered(self) -> None:
        resp = self.client().post(
            "/auth/resend-confirmation",
            json={"email": ""},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}"

    # ── two-factor (TOTP) ─────────────────────────────────────────────────────
    def enroll_totp(self) -> None:
        import pyotp

        resp = self.client().post("/profile/2fa/enroll", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"enroll: {resp.status_code} {resp.text}"
        data = resp.json()
        self._totp_secret = data["secret"]
        code = pyotp.TOTP(self._totp_secret).now()
        self.response = self.client().post(
            "/profile/2fa/verify",
            json={"factor_id": data["factor_id"], "code": code},
            headers={"accept": "application/json"},
        )
        assert self.response.status_code == 200, (
            f"verify enrolment: {self.response.status_code} {self.response.text}"
        )

    def assert_twofa_enabled(self) -> None:
        assert self.response is not None
        assert "Two-factor enabled" in self.response.json().get("message", "")

    def assert_mfa_challenge(self) -> None:
        assert self.response is not None
        body = self.response.json()
        assert body.get("mfa_required") is True, f"no mfa challenge: {body}"
        self._mfa_challenge = body

    def enter_totp_code(self, code: str | None) -> None:
        import pyotp

        if self._mfa_challenge is None and self.response is not None:
            body = self.response.json()
            if body.get("mfa_required"):
                self._mfa_challenge = body
        assert self._mfa_challenge is not None, "no pending mfa challenge"
        if code is None:
            assert self._totp_secret is not None, "no enrolled secret"
            code = pyotp.TOTP(self._totp_secret).now()
        self.response = self.client().post(
            "/auth/mfa",
            json={
                "code": code,
                "factor_id": self._mfa_challenge["factor_id"],
                "challenge_id": self._mfa_challenge["challenge_id"],
            },
            headers={"accept": "application/json"},
        )

    def assert_totp_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 401, f"expected 401, got {self.response.status_code}"

    def assert_twofa_not_offered(self) -> None:
        resp = self.client().post("/profile/2fa/enroll", headers={"accept": "application/json"})
        assert resp.status_code == 404, f"expected 404, got {resp.status_code}"

    # ── OAuth social sign-in ───────────────────────────────────────────────────
    def _login_page_html(self) -> str:
        resp = self.client_for(VISITOR).get("/auth/login", headers={"accept": "text/html"})
        assert resp.status_code == 200, f"GET /auth/login: {resp.status_code}"
        return resp.text

    def assert_oauth_offered(self, provider: str) -> None:
        assert f'data-oauth-provider="{provider}"' in self._login_page_html(), (
            f"no {provider} button on the sign-in page"
        )

    def assert_oauth_not_offered(self, provider: str) -> None:
        assert f'data-oauth-provider="{provider}"' not in self._login_page_html(), (
            f"unexpected {provider} button on the sign-in page"
        )

    def start_oauth(self, provider: str) -> None:
        self.response = self.client_for(VISITOR).get(
            f"/auth/oauth/{provider}", headers={"accept": "text/html"}
        )

    def assert_oauth_authorize_redirect(self, provider: str) -> None:
        assert self.response is not None
        assert self.response.status_code == 303, f"expected 303, got {self.response.status_code}"
        location = self.response.headers.get("location", "")
        assert "/auth/v1/authorize" in location, f"unexpected redirect: {location}"
        assert f"provider={provider}" in location, f"unexpected provider in: {location}"
        cookies = self.response.headers.get_list("set-cookie")
        assert any(c.startswith("oauth_code_verifier=") for c in cookies), (
            "PKCE verifier cookie not parked"
        )

    # ── Passkeys ───────────────────────────────────────────────────────────────
    def assert_passkey_signin_offered(self) -> None:
        assert "data-passkey-signin" in self._login_page_html(), "no passkey button"

    def assert_passkey_signin_not_offered(self) -> None:
        assert "data-passkey-signin" not in self._login_page_html(), "unexpected passkey button"

    def add_passkey(self) -> None:
        self._passkey_device = PasskeyDevice()
        self._passkey_email = self._acting_email
        resp = self.client().post("/profile/passkeys/options")
        assert resp.status_code == 200, f"passkey options: {resp.status_code} {resp.text}"
        registration = resp.json()
        credential = self._passkey_device.create_credential(registration)
        resp = self.client().post(
            "/profile/passkeys/verify",
            json={"challenge_id": registration["challenge_id"], "credential": credential},
        )
        assert resp.status_code == 200, f"passkey verify: {resp.status_code} {resp.text}"

    def assert_passkey_listed(self) -> None:
        resp = self.client().get("/profile", headers={"accept": "text/html"})
        assert resp.status_code == 200
        assert "data-passkey-name" in resp.text, "no passkey listed on the profile"

    def sign_in_with_passkey(self) -> None:
        device = getattr(self, "_passkey_device", None)
        assert device is not None, "add_passkey was not called"
        client = self.client_for(VISITOR)
        resp = client.post("/auth/passkeys/options")
        assert resp.status_code == 200, f"auth options: {resp.status_code} {resp.text}"
        authentication = resp.json()
        assertion = device.get_assertion(authentication)
        self.response = client.post(
            "/auth/passkeys/verify",
            json={"challenge_id": authentication["challenge_id"], "credential": assertion},
        )
        if self.response.status_code == 200:
            self.adopt_current_client(self._passkey_email)

    # ── user management (console accounts screen) ─────────────────────────────
    def _accounts_as_admin(self) -> None:
        as_admin = getattr(self, "_as_admin", None)  # console mixin
        assert as_admin is not None
        as_admin()

    def open_accounts_screen(self) -> None:
        self._accounts_as_admin()
        self.response = self.client().get(
            "/console/accounts", headers={"accept": "application/json"}
        )
        assert self.response.status_code == 200, (
            f"GET /console/accounts: {self.response.status_code} {self.response.text}"
        )

    def _accounts(self) -> list[dict]:
        self.open_accounts_screen()
        assert self.response is not None
        return self.response.json()["accounts"]

    def assert_account_listed(self, email: str) -> None:
        emails = [a["email"] for a in self._accounts()]
        assert email in emails, f"{email!r} not in {emails}"

    def assert_account_not_listed(self, email: str) -> None:
        emails = [a["email"] for a in self._accounts()]
        assert email not in emails, f"{email!r} still listed"

    def filter_accounts(self, query: str) -> None:
        self._accounts_as_admin()
        self.response = self.client().get(
            "/console/accounts", params={"q": query}, headers={"accept": "application/json"}
        )
        assert self.response.status_code == 200, (
            f"GET /console/accounts?q=: {self.response.status_code} {self.response.text}"
        )

    def _filtered_emails(self) -> list[str]:
        assert self.response is not None
        return [a["email"] for a in self.response.json()["accounts"]]

    def assert_account_in_filtered_list(self, email: str) -> None:
        emails = self._filtered_emails()
        assert email in emails, f"{email!r} not in filtered list {emails}"

    def assert_account_not_in_filtered_list(self, email: str) -> None:
        emails = self._filtered_emails()
        assert email not in emails, f"{email!r} unexpectedly in filtered list {emails}"

    def set_account_state(self, email: str, action: str) -> None:
        account = next((a for a in self._accounts() if a["email"] == email), None)
        assert account is not None, f"no account {email!r}"
        resp = self.client().post(
            f"/console/accounts/{account['id']}/{action}",
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 200, f"{action}: {resp.status_code} {resp.text}"

    def try_open_accounts_screen(self) -> None:
        self.response = self.client().get(
            "/console/accounts", headers={"accept": "application/json"}
        )

    def try_open_accounts_screen_as_admin(self) -> None:
        self._accounts_as_admin()
        self.try_open_accounts_screen()

    def assert_redirected_to_dashboard(self) -> None:
        assert self.response is not None
        is_303 = self.response.status_code == 303 and "/profile" in self.response.headers.get(
            "location", ""
        )
        is_hx = self.response.headers.get("hx-redirect") == "/profile"
        is_json = self.response.status_code == 200 and "access_token" in self.response.json()
        assert is_303 or is_hx or is_json, (
            f"Expected 303 redirect to /profile, HX-Redirect, or JSON 200 with access_token, "
            f"got status={self.response.status_code} "
            f"location={self.response.headers.get('location')!r}"
        )

    def assert_registration_successful(self) -> None:
        assert self.response is not None
        is_303 = self.response.status_code == 303 and "/auth/login" in self.response.headers.get(
            "location", ""
        )
        is_json = self.response.status_code == 201
        assert is_303 or is_json, (
            f"Expected 303 redirect to /auth/login or JSON 201, "
            f"got status={self.response.status_code} "
            f"location={self.response.headers.get('location')!r}"
        )
        assert self.last_registered_email is not None
        assert find_users(self.last_registered_email), (
            f"User {self.last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 400, f"Expected 400, got {self.response.status_code}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        assert self.response is not None
        ct = self.response.headers.get("content-type", "")
        is_json_resp = ct.startswith("application/json")
        body = self.response.json().get("detail", "") if is_json_resp else self.response.text
        assert message in body, f"'{message}' not found in:\n{str(body)[:500]}"

    # ── impersonation ──────────────────────────────────────────────────────────

    def _profile_email(self) -> str:
        resp = self.client().get("/profile", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"GET /profile: {resp.status_code} {resp.text}"
        return resp.json().get("email", "")

    def impersonate(self, email: str) -> None:
        self.response = self.client().post("/auth/impersonate", data={"email": email})
        assert self.response.status_code in (200, 303), (
            f"impersonate: {self.response.status_code} {self.response.text}"
        )

    def impersonate_from_accounts(self, email: str) -> None:
        # The accounts row renders a "View as user" form posting the target email;
        # assert the button is on the HTML page, then drive the endpoint behind it.
        listing = self.client().get("/console/accounts", headers={"accept": "text/html"})
        assert listing.status_code == 200, f"GET /console/accounts: {listing.status_code}"
        assert "View as user" in listing.text, "accounts list is missing the impersonate button"
        self.impersonate(email)

    def assert_viewing_as(self, email: str) -> None:
        assert self._profile_email() == email, f"not viewing as {email!r}"

    def assert_impersonation_banner(self) -> None:
        # The API face of the banner: the stash cookie that renders it is present.
        assert "impersonator_access_token" in self.client().cookies

    def stop_impersonating(self) -> None:
        self.response = self.client().post("/auth/impersonate/stop")
        assert self.response.status_code in (200, 303), f"stop: {self.response.status_code}"

    def assert_back_as_admin(self, email: str) -> None:
        assert self._profile_email() == email
        assert "impersonator_access_token" not in self.client().cookies
        console = self.client().get("/console", headers={"accept": "application/json"})
        assert console.status_code == 200, "restored session should reach the console"

    def try_impersonate(self, email: str) -> None:
        self.response = self.client().post("/auth/impersonate", data={"email": email})

    def assert_impersonation_refused(self) -> None:
        assert self.response is not None
        # Non-admins get the console treatment: a plain 404, never a confirmation.
        assert self.response.status_code == 404, f"Expected 404, got {self.response.status_code}"
