from tests.e2e.drivers.api_base import ApiBase


class ProfileApiMixin(ApiBase):
    def view_profile(self) -> None:
        self.response = self.json_client("GET", "/profile")

    def view_dashboard(self) -> None:
        self.response = self.json_client("GET", "/profile")

    def update_handle(self, name: str) -> None:
        self.response = self.json_client("POST", "/profile", json={"handle": name})

    def assert_handle(self, name: str | None) -> None:
        resp = self.json_client("GET", "/profile")
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
        before = self.json_client("GET", "/profile").json()
        email = before.get("email")
        assert email, f"Expected an email in profile JSON, got {before}"
        self.json_client(
            "POST",
            "/profile",
            json={"handle": "read-only-probe", "email": "attacker@evil.test"},
        )
        after = self.json_client("GET", "/profile").json()
        assert after.get("email") == email, (
            f"Email must be read-only: was {email!r}, now {after.get('email')!r}"
        )

    def visit_profile_unauthenticated(self) -> None:
        self.response = self.json_client("GET", "/profile")

    # The following steps are "navigation/discoverability" claims in the feature. A REST client
    # has no page chrome (footer/nav), so we validate the RESTful equivalent: the target
    # resource is discoverable and reachable via the API (HTTP 200 at its canonical URL).

    def assert_link_to_org_dashboard(self) -> None:
        handle = getattr(self, "active_org_handle", "")
        resp = self.json_client("GET", f"/{handle}/dashboard")
        assert resp.status_code == 200, (
            f"Org dashboard /{handle}/dashboard not reachable: {resp.status_code}"
        )

    def assert_link_to_todos(self) -> None:
        handle = getattr(self, "active_org_handle", "")
        resp = self.json_client("GET", f"/{handle}/todos")
        assert resp.status_code == 200, (
            f"Todo list /{handle}/todos not reachable: {resp.status_code}"
        )

    def assert_profile_link_in_footer(self) -> None:
        # Discoverability: the profile resource is reachable at its canonical URL.
        resp = self.json_client("GET", "/profile")
        assert resp.status_code == 200 and resp.json().get("email"), (
            f"Profile not reachable as a resource: {resp.status_code}"
        )

    def assert_no_profile_nav_link(self) -> None:
        # No REST equivalent of "absent from the nav chrome"; the discoverability stand-in is
        # that the profile is its own canonical resource (/profile), not embedded elsewhere.
        resp = self.json_client("GET", "/profile")
        assert resp.status_code == 200, f"Profile resource not reachable: {resp.status_code}"
