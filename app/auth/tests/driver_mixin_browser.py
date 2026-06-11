from uuid import uuid4

from app.shared.config import get_settings
from tests.e2e.drivers.protocols import BrowserProtocol


class AuthBrowserMixin(BrowserProtocol):
    def _admin_headers(self) -> dict:
        return {
            "apikey": get_settings().supabase_service_role_key,
            "Authorization": f"Bearer {get_settings().supabase_service_role_key}",
        }

    def _delete_user_if_exists(self, email: str) -> None:
        assert self._context
        resp = self._context.request.get(
            f"{get_settings().supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        for user in resp.json().get("users", []):
            self._context.request.delete(
                f"{get_settings().supabase_url}/auth/v1/admin/users/{user['id']}",
                headers=self._admin_headers(),
            )

    def sign_in(self, email: str, password: str) -> None:
        self._p.goto(f"{self._base_url}/auth/login")
        self._p.fill("input[name=email]", email)
        self._p.fill("input[name=password]", password)
        with self._p.expect_response(
            lambda r: "/auth/login" in r.url and r.request.method == "POST"
        ):
            self._p.click("button[type=submit]")
        self._p.wait_for_load_state("domcontentloaded")

    def ensure_registered(self, email: str, password: str) -> None:
        assert self._context
        self._context.request.post(
            f"{self._base_url}/auth/register",
            form={"email": email, "password": password},
        )

    def register(self, email: str, password: str) -> None:
        self._last_registered_email = email
        self._p.goto(f"{self._base_url}/auth/register")
        self._p.fill("input[name=email]", email)
        self._p.fill("input[name=password]", password)
        with self._p.expect_response(
            lambda r: "/auth/register" in r.url and r.request.method == "POST"
        ) as resp_info:
            self._p.click("button[type=submit]")
        self._last_response = resp_info.value
        self._p.wait_for_load_state("domcontentloaded")

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def _store_active_org_slug(self) -> None:
        assert self._context
        resp = self._context.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        if resp.status == 200:
            orgs = resp.json()
            if orgs:
                self._active_org_slug = orgs[0]["slug"]  # type: ignore[attr-defined]

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_org_slug()

    def logout_action(self) -> None:
        self._p.goto(f"{self._base_url}/auth/login", wait_until="networkidle")
        self._p.evaluate(
            "fetch('/auth/logout', {method:'POST'}).then(r => { if(r.headers.get('hx-redirect')) window.location = r.headers.get('hx-redirect'); })"
        )
        self._p.wait_for_url(f"{self._base_url}/auth/login", timeout=5000)

    def assert_unauthorized(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 401, (
            f"Expected 401, got {self._last_response.status} at {self._p.url}"
        )

    def assert_redirected_to_login(self) -> None:
        assert "/auth/login" in self._p.url, f"Expected redirect to /auth/login, got {self._p.url}"

    def assert_login_rejected(self) -> None:
        # HTMX 2.x drops 4xx responses without swapping — verify by checking
        # we were not redirected to the dashboard (i.e., sign-in was refused)
        assert "/dashboard" not in self._p.url, (
            f"Expected sign-in to fail but ended up at {self._p.url}"
        )

    def assert_redirected_to_dashboard(self) -> None:
        self._p.wait_for_url(f"{self._base_url}/dashboard", timeout=5000)
        assert "/dashboard" in self._p.url, f"Expected /dashboard, got {self._p.url}"

    def assert_registration_successful(self) -> None:
        assert "Vérifiez" in self._p.content(), "'Vérifiez' not found in registration response"
        assert self._last_registered_email is not None
        assert self._context is not None
        resp = self._context.request.get(
            f"{get_settings().supabase_url}/auth/v1/admin/users",
            params={"email": self._last_registered_email},
            headers=self._admin_headers(),
        )
        users = resp.json().get("users", [])
        assert any(u["email"] == self._last_registered_email for u in users), (
            f"User {self._last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 400, f"Expected 400, got {self._last_response.status}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        self._p.wait_for_selector("[class*='red']", timeout=3000)
        assert message in self._p.content(), (
            f"'{message}' not found in page after registration failure"
        )
