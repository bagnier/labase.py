"""Technical substrate to execute browser (e2e) tests via Playwright.

Owns the in-process app server (hypercorn scheduled on a shared BackgroundLoop,
not a subprocess), the Playwright page, the deterministic clock (driven through
the test-only endpoint), HTML assertions and HTMX interaction helpers. Feature
mixins inherit this; the concrete BrowserDriver assembles them. No typing
Protocol: this base *is* the shared contract.
"""

import asyncio
import os
import socket
import time

from hypercorn.asyncio import serve
from hypercorn.config import Config
from playwright.sync_api import Browser, Page, Response, sync_playwright

from app.main import app
from tests.e2e import cleanup
from tests.e2e.drivers.background_loop import BackgroundLoop


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_event() -> asyncio.Event:
    """Create the shutdown Event inside the background loop it will be awaited on."""
    return asyncio.Event()


class BrowserBase:
    def __init__(self) -> None:
        self._base_url: str = os.environ.get("APP_URL", "")
        self._bg: BackgroundLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._server_future = None
        self._pw = None
        self._browser = None
        self._context = None
        self._page: Page | None = None
        self._last_response: Response | None = None
        self._last_registered_email: str | None = None
        self._active_org_handle: str = ""
        self._primary_email: str = ""
        self._secondary_browser_contexts: dict = {}
        self._acting_as_email: str = ""
        self._primary_context_backup = None

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._base_url:
            port = _free_port()
            self._base_url = f"http://127.0.0.1:{port}"
            # In-process server: hypercorn scheduled on a daemon-thread event loop,
            # so the test and the app share memory (enables monkeypatching). Playwright
            # still drives a real browser, so we bind a real TCP port.
            self._bg = BackgroundLoop()
            self._bg.start()
            config = Config()
            config.bind = [f"127.0.0.1:{port}"]
            config.accesslog = config.errorlog = None
            self._shutdown = self._bg.run(_make_event())
            self._server_future = self._bg.submit(
                serve(app, config, shutdown_trigger=self._shutdown.wait)
            )
            self._wait_for_server()

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        self._open_context()

    def _open_context(self) -> None:
        assert self._browser
        self._context = self._browser.new_context()
        self._page = self._context.new_page()

    def _wait_for_server(self, timeout: float = 30.0) -> None:
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
        self._stop_server()

    def _stop_server(self) -> None:
        if not self._bg:
            return
        if self._shutdown:
            self._bg.call_soon(self._shutdown.set)
        if self._server_future:
            # Let serve() shut down gracefully while the loop is still running,
            # then tear the loop down — avoids "Task was destroyed" warnings.
            self._server_future.result(timeout=10)
        self._bg.stop()
        self._bg = None
        self._shutdown = None
        self._server_future = None

    def reset_session(self) -> None:
        for ctx in self._secondary_browser_contexts.values():
            ctx.close()
        self._secondary_browser_contexts = {}
        if self._context:
            self._context.close()
        self._open_context()
        self._last_response = None
        self._active_org_handle = ""
        self._primary_email = ""
        self._acting_as_email = ""
        self._primary_context_backup = None
        self._org_list_response = None  # type: ignore[attr-defined]

    @property
    def _p(self) -> Page:
        assert self._page
        return self._page

    @property
    def _b(self) -> Browser:
        assert self._browser
        return self._browser

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        """No transaction wrapping: the app runs in its own process."""

    def teardown_test(self) -> None:
        """Truncate app tables. Feature mixins extend this (via super())."""
        cleanup.truncate_app_tables()

    # ── HTMX interaction helpers (real button clicks) ──────────────────────────
    def _arm_dialogs(self, page) -> None:
        """Auto-accept hx-confirm dialogs, once per page."""
        armed = getattr(self, "_dialogs_armed", None)
        if armed is None:
            armed = self._dialogs_armed = set()
        if id(page) not in armed:
            page.on("dialog", lambda d: d.accept())
            armed.add(id(page))

    def _click_and_capture(self, page, selector: str, method: str, path_token: str):
        """Click a control and return the HTMX response it triggers."""
        self._arm_dialogs(page)
        with page.expect_response(
            lambda r: path_token in r.url and r.request.method == method
        ) as info:
            page.click(selector)
        return info.value

    # ── cross-feature methods (real impl provided by feature mixins) ───────────
    def sign_in(self, email: str, password: str) -> None: ...

    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...
