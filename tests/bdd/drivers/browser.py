import os
import socket
import subprocess
import sys
import time
from uuid import uuid4

from playwright.sync_api import Page, Response, sync_playwright

from app.shared.config import get_settings


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserDriver:
    def __init__(self) -> None:
        self._base_url: str = os.environ.get("APP_URL", "")
        self._server: subprocess.Popen | None = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page: Page | None = None
        self._last_response: Response | None = None
        self._last_registered_email: str | None = None

    def start(self) -> None:
        if not self._base_url:
            port = _free_port()
            self._base_url = f"http://127.0.0.1:{port}"
            self._server = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._wait_for_server()

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def _wait_for_server(self, timeout: float = 10.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", int(self._base_url.split(":")[-1])), timeout=0.5
                ):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"Server did not start within {timeout}s")

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        if self._server:
            self._server.terminate()
            self._server.wait(timeout=10)

    def reset_session(self) -> None:
        if self._context:
            self._context.close()
        assert self._browser
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        self._last_response = None

    @property
    def _p(self) -> Page:
        assert self._page
        return self._page

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

    def _delete_user_if_exists(self, email: str) -> None:
        assert self._context
        resp = self._context.request.get(
            f"{get_settings().supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers={
                "apikey": get_settings().supabase_service_role_key,
                "Authorization": f"Bearer {get_settings().supabase_service_role_key}",
            },
        )
        for user in resp.json().get("users", []):
            self._context.request.delete(
                f"{get_settings().supabase_url}/auth/v1/admin/users/{user['id']}",
                headers={
                    "apikey": get_settings().supabase_service_role_key,
                    "Authorization": f"Bearer {get_settings().supabase_service_role_key}",
                },
            )

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def logout_action(self) -> None:
        self._p.goto(f"{self._base_url}/auth/login", wait_until="networkidle")
        self._p.evaluate(
            "fetch('/auth/logout', {method:'POST'}).then(r => { if(r.headers.get('hx-redirect')) window.location = r.headers.get('hx-redirect'); })"
        )
        self._p.wait_for_url(f"{self._base_url}/auth/login", timeout=5000)

    def visit(self, path: str) -> None:
        self._last_response = self._p.goto(f"{self._base_url}{path}", wait_until="networkidle")

    def assert_page_accessible(self, path: str, contains: str) -> None:
        self._p.goto(f"{self._base_url}{path}", wait_until="networkidle")
        assert contains in self._p.content(), f"'{contains}' not found on {path}"

    def assert_text(self, text: str) -> None:
        assert text in self._p.content(), f"'{text}' not found in page content"

    def assert_unauthorized(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 401, (
            f"Expected 401, got {self._last_response.status} at {self._p.url}"
        )

    def assert_redirected_to_login(self) -> None:
        assert "/auth/login" in self._p.url, f"Expected redirect to /auth/login, got {self._p.url}"

    def assert_page_loaded(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, f"Expected 200, got {self._last_response.status}"

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
            headers={
                "apikey": get_settings().supabase_service_role_key,
                "Authorization": f"Bearer {get_settings().supabase_service_role_key}",
            },
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

    # --- Auth (generic) ---

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)

    # --- Dashboard ---

    def view_dashboard(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/dashboard", wait_until="networkidle")

    def assert_link_to_todos(self) -> None:
        assert self._p.query_selector("a[href='/todos']") is not None, (
            "No link to /todos found on dashboard"
        )

    # --- Todo ---

    def _dom_todo_rows(self) -> list:
        return self._p.locator("#todo-list > div").all()

    def _dom_todo_titles(self) -> list[str]:
        return [row.locator("span.flex-1").inner_text().strip() for row in self._dom_todo_rows()]

    def _dom_todo_id_by_title(self, title: str) -> str:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                return row.locator("input[data-todo-id]").get_attribute("data-todo-id") or ""
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def _api_todo_ids(self) -> dict[str, str]:
        assert self._context
        resp = self._context.request.get(
            f"{self._base_url}/todos",
            headers={"accept": "application/json"},
        )
        return {t["title"]: t["id"] for t in resp.json()}

    def have_todo_items(self, titles: list[str]) -> None:
        assert self._context
        for title in reversed(titles):
            self._context.request.post(
                f"{self._base_url}/todos",
                form={"title": title},
            )

    def view_todo_list(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")

    def _goto_todos(self) -> None:
        self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")

    def _wait_htmx_response(self, url_fragment: str, method: str, action: callable) -> None:
        with self._p.expect_response(
            lambda r: url_fragment in r.url and r.request.method == method, timeout=10000
        ):
            action()
        self._goto_todos()

    def add_todo(self, title: str) -> None:
        self._goto_todos()
        self._p.fill("input[name=title]", title)
        self._wait_htmx_response(
            "/todos",
            "POST",
            lambda: self._p.locator("form[hx-post='/todos'] button[type=submit]").click(),
        )

    def mark_todo_done(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self._wait_htmx_response(
            f"/todos/{todo_id}",
            "PATCH",
            lambda: self._p.click(f"input[data-todo-id='{todo_id}']"),
        )

    def rename_todo(self, title: str, new_title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        assert self._context
        self._context.request.patch(
            f"{self._base_url}/todos/{todo_id}",
            form={"title": new_title},
        )
        self._goto_todos()

    def delete_todo(self, title: str) -> None:
        self._goto_todos()
        todo_id = self._dom_todo_id_by_title(title)
        self._wait_htmx_response(
            f"/todos/{todo_id}",
            "DELETE",
            lambda: self._p.click(f"button[data-delete-id='{todo_id}']"),
        )

    def move_todo_above(self, title: str, above: str) -> None:
        self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")
        ids = {t: self._dom_todo_id_by_title(t) for t in (title, above)}
        assert self._context
        self._context.request.post(
            f"{self._base_url}/todos/reorder",
            data={"id": ids[title], "above_id": ids[above]},
        )
        self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")

    def move_todo_to_end(self, title: str) -> None:
        self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")
        todo_id = self._dom_todo_id_by_title(title)
        assert self._context
        self._context.request.post(
            f"{self._base_url}/todos/reorder",
            data={"id": todo_id},
        )
        self._p.goto(f"{self._base_url}/todos", wait_until="networkidle")

    def assert_todo_list_order(self, titles: list[str]) -> None:
        actual = self._dom_todo_titles()
        assert actual == titles, f"Expected order {titles}, got {actual}"

    def assert_todo_visible(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title in titles, f"'{title}' not found in #todo-list DOM: {titles}"

    def assert_todo_completed(self, title: str) -> None:
        for row in self._dom_todo_rows():
            if row.locator("span.flex-1").inner_text().strip() == title:
                span = row.locator("span.flex-1")
                classes = span.get_attribute("class") or ""
                assert "line-through" in classes, f"Todo '{title}' is not shown as completed in DOM"
                return
        raise AssertionError(f"Todo '{title}' not found in DOM")

    def assert_todo_absent(self, title: str) -> None:
        titles = self._dom_todo_titles()
        assert title not in titles, (
            f"'{title}' should be absent but found in #todo-list DOM: {titles}"
        )
