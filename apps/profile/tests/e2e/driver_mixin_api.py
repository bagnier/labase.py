from datetime import UTC, datetime

import httpx

from apps.auth.tests.given_helpers import delete_user_if_exists
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.api_base import ApiBase


class ProfileApiMixin(ApiBase):
    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self._email_change_requested_at: datetime | None = None
        super().reset_session()

    # ── email change ──────────────────────────────────────────────────────────
    def request_email_change(self, new_email: str, password: str) -> None:
        # Self-healing (register_disposable pattern): a previous run's confirmed
        # change leaves the new address registered; GoTrue refuses reusing it.
        delete_user_if_exists(new_email)
        self._track_auth_email(new_email)  # the confirmed user carries this email at teardown
        self._email_change_requested_at = datetime.now(UTC)
        self.response = self.client().post(
            "/profile/email",
            json={"new_email": new_email, "current_password": password},
            headers={"accept": "application/json"},
        )

    def assert_email_change_pending(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 200, (
            f"expected 200, got {self.response.status_code} {self.response.text}"
        )
        assert "confirmation email" in self.response.json().get("message", "")

    def assert_email_change_delivered(self, new_email: str) -> None:
        assert self._email_change_requested_at is not None, "no email change requested"
        mailbox.wait_for_message(
            to=new_email, containing="token_hash=", since=self._email_change_requested_at
        )

    def confirm_email_change(self, new_email: str) -> None:
        assert self._email_change_requested_at is not None, "no email change requested"
        token_hash = mailbox.token_hash_from_mail(new_email, since=self._email_change_requested_at)
        resp = self.client().get(
            f"/auth/confirm-email?token_hash={token_hash}", follow_redirects=False
        )
        assert resp.status_code == 303, f"confirm failed: {resp.status_code} {resp.text}"
        assert resp.headers.get("location") == "/profile", resp.headers.get("location")
        self.rekey_acting_identity(new_email)

    def assert_email_change_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 400, (
            f"expected 400, got {self.response.status_code} {self.response.text}"
        )

    def assert_email_change_not_offered(self) -> None:
        # REST face of "the option is gone": the endpoint itself answers 404.
        resp = self.client().post(
            "/profile/email",
            json={"new_email": "probe@labase.dev", "current_password": "x"},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code} {resp.text}"

    # ── account deletion ──────────────────────────────────────────────────────
    def delete_account(self, password: str) -> None:
        # text/html accept: success is the 303 to the sign-in page, like a browser.
        self.response = self.client().request(
            "DELETE",
            "/profile",
            json={"current_password": password},
            headers={"accept": "text/html"},
        )

    def assert_account_deletion_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 400, f"expected 400, got {self.response.status_code}"

    def assert_account_deletion_not_offered(self) -> None:
        resp = self.client().request(
            "DELETE",
            "/profile",
            json={"current_password": "x"},
            headers={"accept": "application/json"},
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code} {resp.text}"

    # ── avatar & handle switches ──────────────────────────────────────────────
    def upload_avatar(self, filename: str, content: bytes, mime: str) -> None:
        self.response = self.client().post(
            "/profile/avatar",
            files={"file": (filename, content, mime)},
            headers={"accept": "application/json"},
        )

    def assert_avatar_shown(self) -> None:
        me = self.client().get("/profile", headers={"accept": "application/json"}).json()
        assert me.get("avatar_path"), f"no avatar_path in profile: {me}"
        image = self.client().get(f"/profile/avatar/{me['auth_user_id']}")
        assert image.status_code == 200, f"avatar not served: {image.status_code}"
        assert image.headers["content-type"].startswith("image/")

    def assert_avatar_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 400, f"expected 400, got {self.response.status_code}"

    def assert_avatar_not_offered(self) -> None:
        self.upload_avatar("probe.png", b"\x89PNG", "image/png")
        assert self.response is not None
        assert self.response.status_code == 404, f"expected 404, got {self.response.status_code}"

    def assert_handle_not_offered(self) -> None:
        resp = self.client().post(
            "/profile", json={"handle": "probe"}, headers={"accept": "application/json"}
        )
        assert resp.status_code == 404, f"expected 404, got {resp.status_code} {resp.text}"

    def view_profile(self) -> None:
        self.response = self.client().get("/profile")

    def view_dashboard(self) -> None:
        self.response = self.client().get("/profile")

    def update_handle(self, name: str) -> None:
        self.response = self.client().post("/profile", json={"handle": name})

    def assert_handle(self, name: str | None) -> None:
        resp = self.client().get("/profile")
        assert resp.status_code == 200, f"GET /profile returned {resp.status_code}"
        if name:
            assert resp.json().get("handle") == name, (
                f"Expected handle '{name}' in profile JSON, got {resp.json()}"
            )

    def assert_last_update_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code in (422, 409), (
            f"Expected 422/409, got {self.response.status_code}"
        )

    def assert_email_read_only(self) -> None:
        # REST translation of "email is read-only": the API surfaces the email but exposes no
        # way to mutate it (POST /profile only accepts `handle`). So we assert the email is
        # returned, then unchanged after an update.
        before = self.client().get("/profile").json()
        email = before.get("email")
        assert email, f"Expected an email in profile JSON, got {before}"
        self.client().post(
            "/profile",
            json={"handle": "read-only-probe", "email": "attacker@evil.test"},
        )
        after = self.client().get("/profile").json()
        assert after.get("email") == email, (
            f"Email must be read-only: was {email!r}, now {after.get('email')!r}"
        )

    def visit_profile_unauthenticated(self) -> None:
        self.response = self.client().get("/profile")

    # The following steps are "navigation/discoverability" claims in the feature. A REST client
    # has no page chrome (footer/nav), so we validate the RESTful equivalent: the target
    # resource is discoverable and reachable via the API (HTTP 200 at its canonical URL).

    def assert_link_to_org_dashboard(self) -> None:
        handle = getattr(self, "active_org_handle", "")
        resp = self.client().get(f"/{handle}/dashboard")
        assert resp.status_code == 200, (
            f"Org dashboard /{handle}/dashboard not reachable: {resp.status_code}"
        )

    def assert_link_to_todos(self) -> None:
        handle = getattr(self, "active_org_handle", "")
        resp = self.client().get(f"/{handle}/todos")
        assert resp.status_code == 200, (
            f"Todo list /{handle}/todos not reachable: {resp.status_code}"
        )
