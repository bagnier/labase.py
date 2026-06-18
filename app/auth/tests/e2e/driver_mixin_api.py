from uuid import uuid4

from app.auth.tests.admin_helpers import find_users
from tests.e2e.drivers.api_base import ApiBase


class AuthApiMixin(ApiBase):
    # ── HTML page access (auth smoke flows) ────────────────────────────────────
    def visit(self, path: str) -> None:
        self._response = self.run(self.client.get(path))

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self.run(self.client.get(path))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_page_loaded(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"

    def _store_active_slug(self) -> None:
        resp = self.json_client("GET", "/organizations")
        if resp.status_code == 200 and resp.json():
            self._active_org_handle = resp.json()[0]["handle"]

    def sign_in(self, email: str, password: str) -> None:
        self._response = self.run(
            self.client.post("/auth/login", data={"email": email, "password": password})
        )
        self._store_active_slug()

    def ensure_registered(self, email: str, password: str) -> None:
        self.run(self.client.post("/auth/register", data={"email": email, "password": password}))
        self.track_auth_email(email)

    def register(self, email: str, password: str) -> None:
        self._last_registered_email = email
        self._response = self.run(
            self.client.post("/auth/register", data={"email": email, "password": password})
        )
        self.track_auth_email(email)

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_slug()

    def logout_action(self) -> None:
        self._response = self.run(self.client.post("/auth/logout"))

    def assert_unauthorized(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"

    def assert_redirected_to_login(self) -> None:
        assert self._response is not None
        hx_redirect = self._response.headers.get("hx-redirect", "")
        is_hx = "/auth/login" in hx_redirect
        is_http = self._response.status_code in (301, 302, 303, 307, 308)
        is_401 = self._response.status_code == 401
        assert is_hx or is_http or is_401, (
            f"Expected redirect to /auth/login or 401, got status={self._response.status_code}"
            f" hx-redirect={hx_redirect!r}"
        )

    def assert_login_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"

    def assert_redirected_to_dashboard(self) -> None:
        assert self._response is not None
        is_303 = self._response.status_code == 303 and "/profile" in self._response.headers.get(
            "location", ""
        )
        is_hx = self._response.headers.get("hx-redirect") == "/profile"
        assert is_303 or is_hx, (
            f"Expected 303 redirect to /profile or HX-Redirect, "
            f"got status={self._response.status_code} "
            f"location={self._response.headers.get('location')!r}"
        )

    def assert_registration_successful(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 303, f"Expected 303, got {self._response.status_code}"
        assert "/auth/login" in self._response.headers.get("location", ""), (
            f"Expected redirect to /auth/login, got {self._response.headers.get('location')!r}"
        )
        assert self._last_registered_email is not None
        assert find_users(self._last_registered_email), (
            f"User {self._last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 400, f"Expected 400, got {self._response.status_code}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        assert self._response is not None
        assert message in self._response.text, (
            f"'{message}' not found in:\n{self._response.text[:500]}"
        )
