"""Technical substrate for browser (e2e) tests: in-process server, Playwright
browser, unified per-user isolated contexts (distinct cookie jars) keyed by
email, and HTMX interaction helpers. Feature mixins inherit this; BrowserDriver
assembles them."""

import os
from collections.abc import Callable

from playwright.sync_api import (
    APIResponse,
    Browser,
    BrowserContext,
    Locator,
    Page,
    Response,
    sync_playwright,
)

from apps.shared.queue import TaskWorker
from tests.e2e import cleanup
from tests.e2e.drivers.server import InProcessServer

_PASSWORD = "Secret1!"
_VISITOR = "visitor"  # sentinel — unauthenticated context, no associated user
VISITOR = _VISITOR  # public alias, mirroring api_base.VISITOR

# Pinned so http://localhost:8801 can sit in supabase/config.toml [auth.webauthn]
# rp_origins — GoTrue verifies the origin signed into WebAuthn ceremonies, and a
# random port could never be allow-listed. Override with LABASE_E2E_PORT when two
# checkouts run browser e2e at once (passkey scenarios then need that origin
# allow-listed too).
_E2E_PORT = 8801


class BrowserBase:
    # Canonical e2e password — mirror of ApiBase.PASSWORD; the per-email contexts
    # sign in with it, so scenarios that only name a user can omit the password.
    PASSWORD = _PASSWORD

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

    # ── shared access-control assertions (phrases live in tests/e2e/steps_common) ─
    def assert_forbidden(self) -> None:
        assert self.last_response is not None, "No response stored — cannot check forbidden"
        assert self.last_response.status == 403, f"Expected 403, got {self.last_response.status}"

    def assert_not_found(self) -> None:
        # Some denials come back through an AJAX/fetch, not a page navigation; a mixin
        # that took that path stashes the status in ``_denied_status`` (absent otherwise,
        # so the plain page-navigation case falls through to ``last_response``).
        status = getattr(self, "_denied_status", None)
        if status is None:
            assert self.last_response is not None, "No response stored — cannot check not-found"
            status = self.last_response.status
        assert status == 404, f"Expected 404, got {status}"

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.base_url:
            self._server = InProcessServer()
            port = int(os.environ.get("LABASE_E2E_PORT", _E2E_PORT))
            self.base_url = self._server.start(port=port)

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

    def drain_task_queue(self) -> None:
        """Deliver queued tasks (e.g. outboxed email) now — the polling worker is
        off under tests. Runs on the in-process server's loop, where the engines live."""
        if self._server is None:
            return  # external APP_URL: that deployment runs its own worker
        worker = TaskWorker(0)
        while self._server.run(worker.tick()):
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
        """Adopt `email` as the acting user, promoting the visitor context if one exists.

        Mirrors ApiBase.set_acting_email: when the freshly-authenticated visitor
        context becomes a named user, re-key it (and its page) rather than spawning
        a second context that would re-register/re-login the same email.
        """
        if _VISITOR in self._contexts and email not in self._contexts:
            self._contexts[email] = self._contexts.pop(_VISITOR)
            if _VISITOR in self._pages:
                self._pages[email] = self._pages.pop(_VISITOR)
        self._acting_email = email

    def rekey_acting_identity(self, email: str) -> None:
        """The acting user changed identity in place (e.g. confirmed an email change):
        their live context keeps its cookies but now answers to the new email."""
        old = self._acting_email
        if old != email:
            if old in self._contexts and email not in self._contexts:
                self._contexts[email] = self._contexts.pop(old)
            if old in self._pages and email not in self._pages:
                self._pages[email] = self._pages.pop(old)
        self._acting_email = email

    def adopt_current_context(self, email: str) -> None:
        """The acting context just authenticated as `email`: key it under that identity.

        Generalizes visitor promotion: whoever's browser submitted the login form
        holds `email`'s session now, whatever that context was keyed before. A stale
        context already keyed `email` is closed — its cookies are dead anyway.
        """
        old = self._acting_email
        if old == email:
            return
        ctx = self._contexts.pop(old, None)
        if ctx is None:
            self._acting_email = email
            return
        stale = self._contexts.pop(email, None)
        if stale is not None:
            stale.close()
        self._pages.pop(email, None)
        self._contexts[email] = ctx
        if old in self._pages:
            self._pages[email] = self._pages.pop(old)
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

    def wait_htmx(
        self, page: Page, method: str, path_token: str, action: Callable[[], None]
    ) -> Response:
        """Run ``action`` and return the HTMX response matching method + path_token."""
        self._arm_dialogs(page)
        with page.expect_response(
            lambda r: path_token in r.url and r.request.method == method
        ) as info:
            action()
        return info.value

    def click_and_capture(
        self, page: Page, target: str | Locator, method: str, path_token: str
    ) -> Response:
        """Click a control and return the HTMX response it triggers.

        ``target`` may be a CSS selector string or a Playwright Locator.
        """
        action = (lambda: page.click(target)) if isinstance(target, str) else target.click
        return self.wait_htmx(page, method, path_token, action)

    def find_row(self, page: Page, list_selector: str, text_selector: str, text: str) -> Locator:
        """Return the row within ``list_selector`` whose ``text_selector`` sub-element
        matches ``text`` exactly."""
        for row in page.locator(list_selector).all():
            if row.locator(text_selector).inner_text().strip() == text:
                return row
        raise AssertionError(f"No row matching {text!r} in {list_selector!r}")

    def row_action(
        self,
        page: Page,
        list_selector: str,
        text_selector: str,
        text: str,
        action_selector: str,
        method: str,
        path_token: str,
    ) -> Response:
        """Find the row matching ``text``, click a control inside it, capture the HTMX
        response it triggers."""
        row = self.find_row(page, list_selector, text_selector, text)
        return self.click_and_capture(page, row.locator(action_selector), method, path_token)

    def submit_labelled_form(
        self,
        page: Page,
        fields: dict[str, str],
        submit: str | Locator,
        *,
        method: str | None = None,
        path_token: str | None = None,
        root: Locator | None = None,
    ) -> Response | None:
        """Fill labelled fields (optionally scoped to ``root``), then submit.

        HTMX forms pass ``method`` + ``path_token`` and get the captured Response
        back; full-page-reload forms omit them and get a plain navigation wait.
        """
        scope = root if root is not None else page
        for label, value in fields.items():
            scope.get_by_label(label).fill(value)
        if method and path_token:
            return self.click_and_capture(page, submit, method, path_token)
        with page.expect_navigation(wait_until="load"):
            if isinstance(submit, str):
                page.click(submit)
            else:
                submit.click()
        return None
