from datetime import UTC, datetime

from apps.auth.tests.given_helpers import delete_user_if_exists
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.browser_base import BrowserBase


class ProfileBrowserMixin(BrowserBase):
    def reset_session(self) -> None:
        self._email_change_requested_at: datetime | None = None
        super().reset_session()

    def _profile_url(self) -> str:
        return f"{self.base_url}/profile"

    def view_profile(self) -> None:
        self.last_response = self.page.goto(self._profile_url(), wait_until="load")

    # ── email change ──────────────────────────────────────────────────────────
    def request_email_change(self, new_email: str, password: str) -> None:
        # Self-healing (register_disposable pattern): a previous run's confirmed
        # change leaves the new address registered; GoTrue refuses reusing it.
        delete_user_if_exists(new_email)
        self._email_change_requested_at = datetime.now(UTC)
        self.page.goto(self._profile_url(), wait_until="load")
        section = self.page.locator("[data-email-change]")
        section.get_by_label("New email").fill(new_email)
        section.get_by_label("Confirm with your password").fill(password)
        section.get_by_role("button", name="Send confirmation link").click()
        self.page.wait_for_load_state("load")

    def assert_email_change_pending(self) -> None:
        alert = self.page.locator(".alert-success", has_text="confirmation email")
        alert.wait_for(timeout=5000)

    def assert_email_change_delivered(self, new_email: str) -> None:
        assert self._email_change_requested_at is not None, "no email change requested"
        mailbox.wait_for_message(
            to=new_email, containing="token_hash=", since=self._email_change_requested_at
        )

    def confirm_email_change(self, new_email: str) -> None:
        # The mail is really fetched from the catcher; following its link is the
        # one legitimate goto (a user clicks it from their mailbox).
        assert self._email_change_requested_at is not None, "no email change requested"
        token_hash = mailbox.token_hash_from_mail(new_email, since=self._email_change_requested_at)
        self.page.goto(
            f"{self.base_url}/auth/confirm-email?token_hash={token_hash}&type=email_change",
            wait_until="load",
        )
        self.rekey_acting_identity(new_email)

    def assert_email_change_rejected(self) -> None:
        alert = self.page.locator(".alert-error", has_text="incorrect")
        alert.wait_for(timeout=5000)

    def assert_email_change_not_offered(self) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        assert self.page.locator("[data-email-change]").count() == 0, (
            "email change form should be hidden when the option is off"
        )

    # ── account deletion ──────────────────────────────────────────────────────
    def delete_account(self, password: str) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        section = self.page.locator("[data-account-deletion]")
        section.get_by_label("Your password").fill(password)
        section.get_by_role("button", name="Delete my account").click()
        self.page.wait_for_load_state("load")

    def assert_account_deletion_rejected(self) -> None:
        alert = self.page.locator("[data-account-deletion] .alert-error", has_text="incorrect")
        alert.wait_for(timeout=5000)

    def assert_account_deletion_not_offered(self) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        assert self.page.locator("[data-account-deletion]").count() == 0, (
            "danger zone should be hidden when the option is off"
        )

    def update_handle(self, name: str) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Handle": name},
            self.page.get_by_role("button", name="Save changes"),
            method="POST",
            path_token="/profile",
        )

    def assert_handle(self, name: str | None) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        value = self.page.get_by_label("Handle").input_value()
        if name:
            assert value == name, f"Expected handle '{name}', got '{value}'"
        else:
            assert value == "", f"Expected empty handle, got '{value}'"

    def assert_last_update_rejected(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status in (422, 409), (
            f"Expected 422/409, got {self.last_response.status}"
        )

    def assert_email_read_only(self) -> None:
        self.page.goto(self._profile_url(), wait_until="load")
        disabled = self.page.locator("input[disabled]")
        assert disabled.count() >= 1, "Expected at least one disabled input on profile page"

    def visit_profile_unauthenticated(self) -> None:
        self.last_response = self.page.goto(self._profile_url(), wait_until="load")

    def assert_link_to_org_dashboard(self) -> None:
        assert self.page.query_selector("a[href*='/dashboard']") is not None, (
            "No link to org dashboard found on profile"
        )

    def view_dashboard(self) -> None:
        self.last_response = self.page.goto(self._profile_url(), wait_until="load")

    def assert_link_to_todos(self) -> None:
        assert self.page.query_selector("a[href*='/todos']") is not None, (
            "No link to /todos found on dashboard"
        )

    def assert_profile_link_in_footer(self) -> None:
        link = self.page.query_selector("aside a[href='/profile']")
        assert link is not None, "No /profile link found in sidebar footer"

    def assert_no_profile_nav_link(self) -> None:
        link = self.page.query_selector("nav a[href='/profile']")
        assert link is None, "Unexpected /profile link found inside <nav>"
