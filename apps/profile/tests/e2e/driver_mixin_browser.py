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

    def _look_at_own_profile(self, email: str) -> None:
        """A switch flipped by an admin is checked on the account it concerns, not on the admin's:
        step onto that actor's browser and follow their own account link to their profile."""
        self.set_acting_email(email)
        self.follow_to_profile()

    def _open_profile_tab(self, label: str) -> None:
        """Profile sections live in client-side daisyUI tabs; check the tab radio so
        its panel is visible before interacting with the controls inside it."""
        self.page.get_by_role("tab", name=label, exact=True).check()

    def view_profile(self) -> None:
        self.last_response = self.follow_to_profile()

    # ── email change ──────────────────────────────────────────────────────────
    def request_email_change(self, new_email: str, password: str) -> None:
        # Self-healing (register_disposable pattern): a previous run's confirmed
        # change leaves the new address registered; GoTrue refuses reusing it.
        delete_user_if_exists(new_email)
        self._email_change_requested_at = datetime.now(UTC)
        self.follow_to_profile()
        self._open_profile_tab("Email")
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

    def assert_email_change_not_offered(self, email: str) -> None:
        self._look_at_own_profile(email)
        assert self.page.locator("[data-email-change]").count() == 0, (
            "email change form should be hidden when the option is off"
        )

    # ── avatar & handle switches ──────────────────────────────────────────────
    def upload_avatar(self, filename: str, content: bytes, mime: str) -> None:
        self.follow_to_profile()
        self._open_profile_tab("Profile")
        self.page.set_input_files(
            "[data-avatar-upload] input[type=file]",
            files=[{"name": filename, "mimeType": mime, "buffer": content}],
        )
        self.page.locator("[data-avatar-upload] button").click()
        self.page.wait_for_load_state("load")

    def assert_avatar_shown(self) -> None:
        self._open_profile_tab("Profile")
        self.page.wait_for_selector("[data-avatar]", timeout=5000)

    def assert_avatar_rejected(self) -> None:
        # A rejected upload full-reloads /profile; the server opens the Profile tab (avatar_error),
        # but open it explicitly so the assertion never races the server-rendered default tab.
        self._open_profile_tab("Profile")
        alert = self.page.locator("[data-avatar-upload] .alert-error")
        alert.wait_for(timeout=5000)

    def assert_avatar_not_offered(self, email: str) -> None:
        self._look_at_own_profile(email)
        assert self.page.locator("[data-avatar-upload]").count() == 0, (
            "avatar upload should be hidden when the option is off"
        )

    def assert_handle_not_offered(self, email: str) -> None:
        self._look_at_own_profile(email)
        assert self.page.locator("[data-handle-form]").count() == 0, (
            "handle form should be hidden when the option is off"
        )

    # ── account deletion ──────────────────────────────────────────────────────
    def delete_account(self, password: str) -> None:
        self.follow_to_profile()
        self._open_profile_tab("Account")
        section = self.page.locator("[data-account-deletion]")
        section.get_by_label("Your password").fill(password)
        section.get_by_role("button", name="Delete my account").click()
        self.page.wait_for_load_state("load")
        self.drain_task_queue()  # run UserDeleted's reactions (reap the orgs, forget the profile)

    def assert_account_deletion_rejected(self) -> None:
        alert = self.page.locator("[data-account-deletion] .alert-error", has_text="incorrect")
        alert.wait_for(timeout=5000)

    def assert_account_deletion_not_offered(self, email: str) -> None:
        self._look_at_own_profile(email)
        assert self.page.locator("[data-account-deletion]").count() == 0, (
            "danger zone should be hidden when the option is off"
        )

    def update_handle(self, name: str) -> None:
        self.follow_to_profile()
        self._open_profile_tab("Profile")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Handle": name},
            self.page.get_by_role("button", name="Save changes"),
            method="POST",
            path_token="/profile",
        )

    def assert_handle(self, name: str | None) -> None:
        # What the *stored* handle is: a refused update leaves the typed value in the field, so
        # reading it back means reloading the page they are on, as a person would.
        self.page.reload(wait_until="load")
        self._open_profile_tab("Profile")
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
        self._open_profile_tab("Email")
        assert self.page.locator("input#email[disabled]").count() == 1, (
            "Expected the sign-in email to be shown as a read-only (disabled) field"
        )

    def visit_profile_unauthenticated(self) -> None:
        self.last_response = self.page.goto(self._profile_url(), wait_until="load")

    def assert_link_to_org_dashboard(self) -> None:
        assert self.page.query_selector("a[href*='/dashboard']") is not None, (
            "No link to org dashboard found on profile"
        )

    def view_dashboard(self) -> None:
        self.last_response = self.follow_to_profile()

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
