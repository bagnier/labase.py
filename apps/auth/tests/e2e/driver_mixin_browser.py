from uuid import uuid4

from apps.auth.tests.given_helpers import delete_user_if_exists, find_users
from tests.e2e.drivers.browser_base import BrowserBase


class AuthBrowserMixin(BrowserBase):
    last_registered_email: str | None

    def reset_session(self) -> None:
        self.last_registered_email = None
        super().reset_session()

    def _delete_user_if_exists(self, email: str) -> None:
        delete_user_if_exists(email)

    # ── HTML page access (auth smoke flows) ────────────────────────────────────
    def visit(self, path: str) -> None:
        self.last_response = self.page.goto(f"{self.base_url}{path}", wait_until="load")

    def assert_page_accessible(self, path: str, contains: str) -> None:
        self.page.goto(f"{self.base_url}{path}", wait_until="load")
        assert contains in self.page.content(), f"'{contains}' not found on {path}"

    def assert_page_loaded(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 200, f"Expected 200, got {self.last_response.status}"

    def sign_in(self, email: str, password: str) -> None:
        self.page.goto(f"{self.base_url}/auth/login")
        resp = self.submit_labelled_form(
            self.page,
            {"Email": email, "Password": password},
            self.page.get_by_role("button", name="Sign in"),
            method="POST",
            path_token="/auth/login",
        )
        assert resp is not None
        if resp.status == 303 or resp.headers.get("hx-redirect"):
            self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)
            self.set_acting_email(email)
        else:
            self.page.wait_for_load_state("domcontentloaded")

    def ensure_registered(self, email: str, password: str) -> None:
        page = self.page.context.new_page()
        page.goto(f"{self.base_url}/auth/register")
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(password)
        page.get_by_role("button", name="Create my account").click()
        page.wait_for_load_state("domcontentloaded")
        page.close()

    def register(self, email: str, password: str) -> None:
        self.last_registered_email = email
        self.page.goto(f"{self.base_url}/auth/register")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Email": email, "Password": password},
            self.page.get_by_role("button", name="Create my account"),
            method="POST",
            path_token="/auth/register",
        )
        self.page.wait_for_load_state("domcontentloaded")

    def register_fresh(self, password: str) -> None:
        self.register(f"{uuid4()}@test.local", password)

    def register_disposable(self, email: str, password: str) -> None:
        self._delete_user_if_exists(email)
        self.register(email, password)

    def _store_active_org_handle(self) -> None:
        # self._page is on /profile after sign_in; extract handle from the org card link
        link = self.page.locator("[data-organisation-card] a[href*='/dashboard']").first
        href = link.get_attribute("href") or ""
        handle = href.strip("/").split("/")[0]
        if handle:
            self.active_org_handle = handle

    def sign_in_as_fresh_user(self) -> None:
        email = f"{uuid4()}@test.local"
        password = "Secret1!"
        self.ensure_registered(email, password)
        self.sign_in(email, password)
        self._store_active_org_handle()

    def logout_action(self) -> None:
        self.page.evaluate("fetch('/auth/logout',{method:'POST'})")
        self.page.goto(f"{self.base_url}/auth/login", wait_until="load")

    def assert_redirected_to_login(self) -> None:
        assert "/auth/login" in self.page.url, (
            f"Expected redirect to /auth/login, got {self.page.url}"
        )

    def assert_login_rejected(self) -> None:
        # HTMX 2.x drops 4xx responses without swapping — verify by checking
        # we were not redirected to the dashboard (i.e., sign-in was refused)
        assert "/profile" not in self.page.url, (
            f"Expected sign-in to fail but ended up at {self.page.url}"
        )

    def assert_redirected_to_dashboard(self) -> None:
        self.page.wait_for_url(f"{self.base_url}/profile", timeout=5000)
        assert "/profile" in self.page.url, f"Expected /profile, got {self.page.url}"

    def assert_registration_successful(self) -> None:
        content = self.page.content()
        assert "Account created" in content, "'Account created' not found in registration response"
        assert self.last_registered_email is not None
        assert find_users(self.last_registered_email), (
            f"User {self.last_registered_email!r} not found in Supabase after registration"
        )

    def assert_registration_failed(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 400, f"Expected 400, got {self.last_response.status}"

    def assert_registration_failed_with_message(self, message: str) -> None:
        self.assert_registration_failed()
        self.page.wait_for_selector(".alert-error", timeout=3000)
        assert message in self.page.content(), (
            f"'{message}' not found in page after registration failure"
        )
