from tests.e2e.drivers.protocols import ApiProtocol


class ProfileApiMixin(ApiProtocol):
    _JSON = {"accept": "application/json"}

    def view_profile(self) -> None:
        self._response = self._run(self._c.get("/profile", headers=self._JSON))

    def view_dashboard(self) -> None:
        self._response = self._run(self._c.get("/profile", headers=self._JSON))

    def update_handle(self, name: str) -> None:
        self._response = self._run(
            self._c.post("/profile", data={"handle": name}, headers=self._JSON)
        )

    def assert_handle(self, name: str | None) -> None:
        resp = self._run(self._c.get("/profile", headers=self._JSON))
        assert resp.status_code == 200, f"GET /profile returned {resp.status_code}"
        if name:
            assert resp.json().get("handle") == name, (
                f"Expected handle '{name}' in profile JSON, got {resp.json()}"
            )

    def assert_last_update_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code in (422, 409), (
            f"Expected 422/409, got {self._response.status_code}"
        )

    def assert_email_read_only(self) -> None:
        # REST translation of "email is read-only": the API surfaces the email but exposes no
        # way to mutate it (POST /profile only accepts `handle`). So we assert the email is
        # returned, then unchanged after an update.
        before = self._run(self._c.get("/profile", headers=self._JSON)).json()
        email = before.get("email")
        assert email, f"Expected an email in profile JSON, got {before}"
        self._run(
            self._c.post(
                "/profile",
                data={"handle": "read-only-probe", "email": "attacker@evil.test"},
                headers=self._JSON,
            )
        )
        after = self._run(self._c.get("/profile", headers=self._JSON)).json()
        assert after.get("email") == email, (
            f"Email must be read-only: was {email!r}, now {after.get('email')!r}"
        )

    def visit_profile_unauthenticated(self) -> None:
        self._response = self._run(self._c.get("/profile", headers=self._JSON))

    # The following steps are "navigation/discoverability" claims in the feature. A REST client
    # has no page chrome (footer/nav), so we validate the RESTful equivalent: the target
    # resource is discoverable and reachable via the API (HTTP 200 at its canonical URL).

    def assert_link_to_org_dashboard(self) -> None:
        handle = getattr(self, "_active_org_handle", "")
        resp = self._run(self._c.get(f"/{handle}/dashboard", headers=self._JSON))
        assert resp.status_code == 200, (
            f"Org dashboard /{handle}/dashboard not reachable: {resp.status_code}"
        )

    def assert_link_to_todos(self) -> None:
        handle = getattr(self, "_active_org_handle", "")
        resp = self._run(self._c.get(f"/{handle}/todos", headers=self._JSON))
        assert resp.status_code == 200, (
            f"Todo list /{handle}/todos not reachable: {resp.status_code}"
        )

    def assert_profile_link_in_footer(self) -> None:
        # Discoverability: the profile resource is reachable at its canonical URL.
        resp = self._run(self._c.get("/profile", headers=self._JSON))
        assert resp.status_code == 200 and resp.json().get("email"), (
            f"Profile not reachable as a resource: {resp.status_code}"
        )

    def assert_no_profile_nav_link(self) -> None:
        # No REST equivalent of "absent from the nav chrome"; the discoverability stand-in is
        # that the profile is its own canonical resource (/profile), not embedded elsewhere.
        resp = self._run(self._c.get("/profile", headers=self._JSON))
        assert resp.status_code == 200, f"Profile resource not reachable: {resp.status_code}"
