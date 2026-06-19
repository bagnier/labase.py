"""Technical substrate for browser (e2e) tests: in-process server, Playwright
browser, unified per-user isolated contexts (distinct cookie jars) keyed by
email, and HTMX interaction helpers. Feature mixins inherit this; BrowserDriver
assembles them."""

import os

from playwright.sync_api import (
    APIResponse,
    Browser,
    BrowserContext,
    Page,
    Response,
    sync_playwright,
)

from tests.e2e import cleanup
from tests.e2e.drivers.server import InProcessServer

_PASSWORD = "Secret1!"
_VISITOR = "visitor"  # sentinel — unauthenticated context, no associated user


class BrowserBase:
    def __init__(self) -> None:
        self.base_url: str = os.environ.get("APP_URL", "")
        self._server: InProcessServer | None = None
        self._playwright = None
        self.__browser: Browser | None = None
        self.last_response: Response | APIResponse | None = None
        # per-user contexts (distinct cookie jars) and their pages, keyed by email
        # (or _VISITOR for the unauthenticated context).
        self._contexts: dict[str, BrowserContext] = {}
        self._pages: dict[str, Page] = {}
        self._acting_email: str = _VISITOR

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.base_url:
            self._server = InProcessServer()
            self.base_url = self._server.start()

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

    def _open_context(self) -> None:
        """Open the unauthenticated (visitor) context and its page."""
        ctx = self._browser.new_context()
        self._contexts[_VISITOR] = ctx
        self._pages[_VISITOR] = ctx.new_page()

    def stop(self) -> None:
        self._close_contexts()
        if self.__browser:
            self.__browser.close()
        if self._playwright:
            self._playwright.stop()
        if self._server:
            self._server.stop()
            self._server = None

    def _close_contexts(self) -> None:
        for ctx in self._contexts.values():
            ctx.close()
        self._contexts = {}
        self._pages = {}

    def reset_session(self) -> None:
        self._close_contexts()
        self._open_context()
        self.last_response = None
        self._acting_email = _VISITOR

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        pass

    def teardown_test(self) -> None:
        cleanup.truncate_app_tables()

    # ── unified multi-user context management ──────────────────────────────────
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
        """Get or create an isolated browser context (distinct cookie jar) for `email`.

        Secondary users (email != _VISITOR) are registered and logged in on creation;
        the visitor context stays unauthenticated.
        """
        if email not in self._contexts:
            ctx = self._browser.new_context()
            if email != _VISITOR:
                self._setup_context(ctx, email)
            self._contexts[email] = ctx
        return self._contexts[email]

    def page_for(self, email: str) -> Page:
        """Get or create the persistent page for `email`'s isolated context."""
        ctx = self.context_for(email)
        if email not in self._pages:
            self._pages[email] = ctx.new_page()
        return self._pages[email]

    @property
    def context(self) -> BrowserContext:
        return self.context_for(self._acting_email)

    @property
    def page(self) -> Page:
        return self.page_for(self._acting_email)

    def set_acting_email(self, email: str) -> None:
        self._acting_email = email

    def clear_acting_email(self) -> None:
        self._acting_email = _VISITOR

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
