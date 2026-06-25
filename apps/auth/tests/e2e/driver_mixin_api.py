from uuid import uuid4

import httpx

from apps.auth.tests.given_helpers import delete_user_if_exists, find_users
from tests.e2e.drivers.api_base import ApiBase


class AuthApiMixin(ApiBase):
    last_registered_email: str | None

    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self.last_registered_email = None
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
            self.set_acting_email(email)
        self._store_active_slug()

    def ensure_registered(self, email: str, password: str) -> None:
        self.client().post("/auth/register", json={"email": email, "password": password})
        self._track_auth_email(email)

    def register(self, email: str, password: str) -> None:
        self.last_registered_email = email
        self.response = self.client().post(
            "/auth/register", json={"email": email, "password": password}
        )
        self._track_auth_email(email)

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
