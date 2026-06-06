import asyncio
from uuid import uuid4

import httpx

from app.main import app
from app.shared.config import settings


class ApiDriver:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )

    def stop(self) -> None:
        if self._client and self._loop:
            self._loop.run_until_complete(self._client.aclose())
        if self._loop:
            self._loop.close()

    def _run(self, coro):
        assert self._loop
        return self._loop.run_until_complete(coro)

    @property
    def _c(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

    def reset_session(self) -> None:
        pass

    def sign_in(self, email: str, password: str) -> None:
        self._response = self._run(
            self._c.post("/auth/login", data={"email": email, "password": password})
        )

    def ensure_registered(self, email: str, password: str) -> None:
        self._run(self._c.post("/auth/register", data={"email": email, "password": password}))

    def register(self, email: str, password: str) -> None:
        self._last_registered_email = email
        self._response = self._run(
            self._c.post("/auth/register", data={"email": email, "password": password})
        )

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def _admin_headers(self) -> dict:
        return {
            "apikey": settings.supabase_service_role_key,
            "Authorization": f"Bearer {settings.supabase_service_role_key}",
        }

    def _delete_user_if_exists(self, email: str) -> None:
        resp = httpx.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        for user in resp.json().get("users", []):
            httpx.delete(
                f"{settings.supabase_url}/auth/v1/admin/users/{user['id']}",
                headers=self._admin_headers(),
            )

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def logout_action(self) -> None:
        self._response = self._run(self._c.post("/auth/logout"))

    def visit(self, path: str) -> None:
        self._response = self._run(self._c.get(path))

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self._run(self._c.get(path))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_text(self, text: str) -> None:
        assert self._response is not None
        assert text in self._response.text, f"'{text}' not found in:\n{self._response.text[:500]}"

    def assert_unauthorized(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"

    def assert_redirected_to_login(self) -> None:
        assert self._response is not None
        hx_redirect = self._response.headers.get("hx-redirect", "")
        is_hx = "/auth/login" in hx_redirect
        is_http = self._response.status_code in (301, 302, 307, 308)
        assert is_hx or is_http, (
            f"Expected redirect to /auth/login, got status={self._response.status_code} hx-redirect={hx_redirect!r}"
        )

    def assert_page_loaded(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"

    def assert_login_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 401, f"Expected 401, got {self._response.status_code}"

    def assert_redirected_to_dashboard(self) -> None:
        assert self._response is not None
        assert self._response.headers.get("hx-redirect") == "/dashboard", (
            f"Expected HX-Redirect to /dashboard, got {self._response.headers.get('hx-redirect')}"
        )

    def assert_registration_successful(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"
        assert "Vérifiez" in self._response.text, "'Vérifiez' not found in registration response"
        assert self._last_registered_email is not None
        resp = httpx.get(
            f"{settings.supabase_url}/auth/v1/admin/users",
            params={"email": self._last_registered_email},
            headers=self._admin_headers(),
        )
        users = resp.json().get("users", [])
        assert any(u["email"] == self._last_registered_email for u in users), (
            f"User {self._last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 400, f"Expected 400, got {self._response.status_code}"
