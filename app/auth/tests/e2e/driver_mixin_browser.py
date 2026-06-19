from uuid import uuid4

from app.auth.tests.admin_helpers import delete_user_if_exists, find_users
from tests.e2e.drivers.browser_base import BrowserBase


class AuthBrowserMixin(BrowserBase):
    def _delete_user_if_exists(self, email: str) -> None:
        delete_user_if_exists(email)

    # ── HTML page access (auth smoke flows) ────────────────────────────────────
    def visit(self, path: str) -> None:
        self._last_response = self._page.goto(f"{self._base_url}{path}", wait_until="load")

    def assert_page_accessible(self, path: str, contains: str) -> None:
        self._page.goto(f"{self._base_url}{path}", wait_until="load")
        assert contains in self._page.content(), f"'{contains}' not found on {path}"

    def assert_page_loaded(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, f"Expected 200, got {self._last_response.status}"

    def sign_in(self, email: str, password: str) -> None:
        self._page.goto(f"{self._base_url}/auth/login")
        self._page.fill("input[name=email]", email)
        self._page.fill("input[name=password]", password)
        with self._page.expect_response(
            lambda r: "/auth/login" in r.url and r.request.method == "POST"
        ) as resp_info:
            self._page.click("button[type=submit]")
        if resp_info.value.status == 303 or resp_info.value.headers.get("hx-redirect"):
            self._page.wait_for_url(f"{self._base_url}/profile", timeout=5000)
        else:
            self._page.wait_for_load_state("domcontentloaded")

    def ensure_registered(self, email: str, password: str) -> None:
        page = self._page.context.new_page()
        page.goto(f"{self._base_url}/auth/register")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", password)
        page.click("button[type=submit]")
        page.wait_for_load_state("domcontentloaded")
        page.close()

    def register(self, email: str, password: str) -> None:
        self._last_registered_email = email
        self._page.goto(f"{self._base_url}/auth/register")
        self._page.fill("input[name=email]", email)
        self._page.fill("input[name=password]", password)
        with self._page.expect_response(
            lambda r: "/auth/register" in r.url and r.request.method == "POST"
        ) as resp_info:
            self._page.click("button[type=submit]")
        self._last_response = resp_info.value
        self._page.wait_for_load_state("domcontentloaded")

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def _store_active_org_handle(self) -> None:
        # self._page is on /profile after sign_in; extract handle from the org card link
        link = self._page.locator("[data-organisation-card] a[href*='/dashboard']").first
        href = link.get_attribute("href") or ""
        handle = href.strip("/").split("/")[0]
        if handle:
            self._active_org_handle = handle  # type: ignore[attr-defined]

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_org_handle()

    def logout_action(self) -> None:
        self._page.evaluate("fetch('/auth/logout',{method:'POST'})")
        self._page.goto(f"{self._base_url}/auth/login", wait_until="load")

    def assert_unauthorized(self) -> None:
        # Browser is redirected to /auth/login (302); check final URL
        assert "/auth/login" in self._page.url, f"Expected /auth/login, got {self._page.url}"

    def assert_redirected_to_login(self) -> None:
        assert "/auth/login" in self._page.url, (
            f"Expected redirect to /auth/login, got {self._page.url}"
        )

    def assert_login_rejected(self) -> None:
        # HTMX 2.x drops 4xx responses without swapping — verify by checking
        # we were not redirected to the dashboard (i.e., sign-in was refused)
        assert "/profile" not in self._page.url, (
            f"Expected sign-in to fail but ended up at {self._page.url}"
        )

    def assert_redirected_to_dashboard(self) -> None:
        self._page.wait_for_url(f"{self._base_url}/profile", timeout=5000)
        assert "/profile" in self._page.url, f"Expected /profile, got {self._page.url}"

    def assert_registration_successful(self) -> None:
        assert "verify" in self._page.content(), "'verify' not found in registration response"
        assert self._last_registered_email is not None
        assert find_users(self._last_registered_email), (
            f"User {self._last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 400, f"Expected 400, got {self._last_response.status}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        self._page.wait_for_selector("[class*='red']", timeout=3000)
        assert message in self._page.content(), (
            f"'{message}' not found in page after registration failure"
        )
