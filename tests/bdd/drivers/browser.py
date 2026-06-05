import os
import socket
import subprocess
import sys
import time

from playwright.sync_api import Page, Response, sync_playwright

from tests.bdd.drivers.base import BaseDriver


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserDriver(BaseDriver):
    def __init__(self) -> None:
        self._base_url: str = os.environ.get("APP_URL", "")
        self._server: subprocess.Popen | None = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page: Page | None = None
        self._last_response: Response | None = None

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

    @property
    def _p(self) -> Page:
        assert self._page
        return self._page

    def login(self, email: str, password: str) -> None:
        self._p.goto(f"{self._base_url}/auth/login")
        self._p.fill("input[name=email]", email)
        self._p.fill("input[name=password]", password)
        with self._p.expect_response(
            lambda r: "/auth/login" in r.url and r.request.method == "POST"
        ):
            self._p.click("button[type=submit]")
        self._p.wait_for_load_state("domcontentloaded")

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
        # we were not redirected to the dashboard (i.e., login was refused)
        assert "/dashboard" not in self._p.url, (
            f"Expected login to fail but ended up at {self._p.url}"
        )
