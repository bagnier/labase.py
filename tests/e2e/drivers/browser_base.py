"""Technical substrate for browser (e2e) tests: in-process hypercorn server,
Playwright browser, per-user isolated contexts (distinct cookie jars), and
HTMX interaction helpers. Feature mixins inherit this; BrowserDriver assembles them."""

import asyncio
import os
import socket
import time

from hypercorn.asyncio import serve
from hypercorn.config import Config
from playwright.sync_api import Browser, BrowserContext, Page, Response, sync_playwright

from app.main import app
from tests.e2e import cleanup
from tests.e2e.drivers.background_loop import BackgroundLoop

_PASSWORD = "Secret1!"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _make_event() -> asyncio.Event:
    return asyncio.Event()


class BrowserBase:
    def __init__(self) -> None:
        self.base_url: str = os.environ.get("APP_URL", "")
        self._bg: BackgroundLoop | None = None
        self._shutdown: asyncio.Event | None = None
        self._server_future = None
        self._playwright = None
        self.__browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.__page: Page | None = None
        self.last_response: Response | None = None
        self.last_registered_email: str | None = None
        self.active_org_handle: str = ""
        self.primary_email: str = ""
        # per-user contexts (distinct cookie jars), keyed by email
        self._contexts: dict[str, BrowserContext] = {}
        self.acting_email: str = ""

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.base_url:
            port = _free_port()
            self.base_url = f"http://127.0.0.1:{port}"
            # In-process server: hypercorn on a daemon-thread event loop so the
            # test and the app share memory (enables monkeypatching).
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

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch()
        self._open_context()

    @property
    def _browser(self) -> Browser:
        assert self.__browser is not None, "_browser accessed before start()"
        return self.__browser

    @_browser.setter
    def _browser(self, value: Browser | None) -> None:
        self.__browser = value

    @property
    def page(self) -> Page:
        assert self.__page is not None, "page accessed before context was opened"
        return self.__page

    @page.setter
    def page(self, value: Page | None) -> None:
        self.__page = value

    def _open_context(self) -> None:
        self._context = self._browser.new_context()
        self.page = self._context.new_page()

    def _wait_for_server(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(
                    ("127.0.0.1", int(self.base_url.split(":")[-1])), timeout=0.5
                ):
                    return
            except OSError:
                time.sleep(0.2)
        raise RuntimeError(f"Server did not start within {timeout}s")

    def stop(self) -> None:
        if self._context:
            self._context.close()
        if self.__browser:
            self.__browser.close()
        if self._playwright:
            self._playwright.stop()
        self._stop_server()

    def _stop_server(self) -> None:
        if not self._bg:
            return
        if self._shutdown:
            self._bg.call_soon(self._shutdown.set)
        if self._server_future:
            self._server_future.result(timeout=10)
        self._bg.stop()
        self._bg = None
        self._shutdown = None
        self._server_future = None

    def reset_session(self) -> None:
        for ctx in self._contexts.values():
            ctx.close()
        self._contexts = {}
        if self._context:
            self._context.close()
        self._open_context()
        self.last_response = None
        self.active_org_handle = ""
        self.primary_email = ""
        self.acting_email = ""

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        pass

    def teardown_test(self) -> None:
        cleanup.truncate_app_tables()

    # ── multi-user context management ──────────────────────────────────────────
    def _setup_context(self, ctx: BrowserContext, email: str) -> None:
        """Register and login `email` in a fresh browser context."""
        page = ctx.new_page()
        page.goto(f"{self.base_url}/auth/register")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", _PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("domcontentloaded")
        page.goto(f"{self.base_url}/auth/login")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", _PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url("**/profile", timeout=10000)
        page.close()

    def context_for(self, email: str) -> BrowserContext:
        """Get or create an isolated browser context (distinct cookie jar) for `email`."""
        if email not in self._contexts:
            ctx = self._browser.new_context()
            self._setup_context(ctx, email)
            self._contexts[email] = ctx
        return self._contexts[email]

    def page_for(self, email: str) -> Page:
        """Get or create the persistent page for `email`'s isolated context."""
        ctx = self.context_for(email)
        if not hasattr(ctx, "_page") or ctx._page is None:
            ctx._page = ctx.new_page()  # type: ignore[attr-defined]
        return ctx._page  # type: ignore[attr-defined]

    # ── HTMX interaction helpers ───────────────────────────────────────────────
    def _arm_dialogs(self, page: Page) -> None:
        """Auto-accept hx-confirm dialogs, once per page."""
        armed = getattr(self, "_dialogs_armed", None)
        if armed is None:
            armed = self._dialogs_armed = set()
        if id(page) not in armed:
            page.on("dialog", lambda d: d.accept())
            armed.add(id(page))

    def click_and_capture(self, page: Page, selector: str, method: str, path_token: str):
        """Click a control and return the HTMX response it triggers."""
        self._arm_dialogs(page)
        with page.expect_response(
            lambda r: path_token in r.url and r.request.method == method
        ) as info:
            page.click(selector)
        return info.value
