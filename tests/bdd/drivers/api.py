import asyncio
from uuid import uuid4

import httpx

from app.main import app
from app.shared.config import get_settings


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
        if self._client and self._loop:
            self._loop.run_until_complete(self._client.aclose())
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )

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
            "apikey": get_settings().supabase_service_role_key,
            "Authorization": f"Bearer {get_settings().supabase_service_role_key}",
        }

    def _delete_user_if_exists(self, email: str) -> None:
        resp = httpx.get(
            f"{get_settings().supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        for user in resp.json().get("users", []):
            httpx.delete(
                f"{get_settings().supabase_url}/auth/v1/admin/users/{user['id']}",
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
            f"{get_settings().supabase_url}/auth/v1/admin/users",
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

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        assert message in self._response.text, (
            f"'{message}' not found in:\n{self._response.text[:500]}"
        )

    # --- Auth (generic) ---

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)

    # --- Dashboard ---

    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/dashboard"))

    def assert_link_to_todos(self) -> None:
        assert self._response is not None
        assert "/todos" in self._response.text, "No link to /todos found on dashboard"

    # --- Todo ---

    def _todo_id_by_title(self, title: str) -> str:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        todos = resp.json()
        for t in todos:
            if t["title"] == title:
                return t["id"]
        raise AssertionError(f"Todo '{title}' not found in list")

    def have_todo_items(self, titles: list[str]) -> None:
        for title in reversed(titles):
            self._run(self._c.post("/todos", data={"title": title}))

    def view_todo_list(self) -> None:
        self._response = self._run(self._c.get("/todos"))

    def add_todo(self, title: str) -> None:
        self._response = self._run(self._c.post("/todos", data={"title": title}))

    def mark_todo_done(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(self._c.patch(f"/todos/{todo_id}", data={"done": "true"}))

    def rename_todo(self, title: str, new_title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(self._c.patch(f"/todos/{todo_id}", data={"title": new_title}))

    def delete_todo(self, title: str) -> None:
        todo_id = self._todo_id_by_title(title)
        self._response = self._run(self._c.delete(f"/todos/{todo_id}"))

    def move_todo_above(self, title: str, above: str) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self._response = self._run(
            self._c.post("/todos/reorder", json={"id": ids[title], "above_id": ids[above]})
        )

    def move_todo_to_end(self, title: str) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        todos = resp.json()
        ids = {t["title"]: t["id"] for t in todos}
        self._response = self._run(
            self._c.post("/todos/reorder", json={"id": ids[title], "above_id": None})
        )

    def assert_todo_list_order(self, titles: list[str]) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        actual = [t["title"] for t in resp.json()]
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        titles = [t["title"] for t in resp.json()]
        assert title in titles, f"'{title}' not found in todo list: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        for t in resp.json():
            if t["title"] == title:
                assert t["done"], f"Todo '{title}' is not marked as done"
                return
        raise AssertionError(f"Todo '{title}' not found")

    def assert_todo_absent(self, title: str) -> None:
        resp = self._run(self._c.get("/todos", headers={"accept": "application/json"}))
        titles = [t["title"] for t in resp.json()]
        assert title not in titles, f"'{title}' should be absent but found in: {titles}"
