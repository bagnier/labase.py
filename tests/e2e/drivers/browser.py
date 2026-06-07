import os
import socket
import subprocess
import sys
import time

from playwright.sync_api import Page, Response, sync_playwright

from app.auth.tests.driver_mixin import AuthBrowserMixin
from app.dashboard.tests.driver_mixin import DashboardBrowserMixin
from app.todo.tests.driver_mixin import TodoBrowserMixin
from tests.e2e.drivers.shared_mixin import SharedBrowserMixin


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class BrowserDriver(AuthBrowserMixin, DashboardBrowserMixin, TodoBrowserMixin, SharedBrowserMixin):
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
