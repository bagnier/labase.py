import httpx

from app.auth.tests.given_helpers import (
    create_user,
    delete_user_if_exists,
    set_admin_role,
)
from tests.e2e.drivers.api_base import ApiBase

_ADMIN_PASSWORD = "Test1234!"


class ConsoleApiMixin(ApiBase):
    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self.settings_response: httpx.Response | None = None
        self._admin_email: str | None = None
        super().reset_session()

    def sign_in_as_admin(self, email: str) -> None:
        # Create + promote out of band (admin API) so the issued JWT carries app_metadata.role,
        # then log in on a dedicated client — base primitives only, no cross-mixin sign_in.
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))
        self._track_auth_email(email)
        client = self._make_client()
        client.post("/auth/login", json={"email": email, "password": _ADMIN_PASSWORD})
        self._clients[email] = client
        self.set_acting_email(email)
        self._admin_email = email

    def _as_admin(self) -> None:
        # Multi-user scenarios sign in other users after the admin; re-target the admin.
        assert self._admin_email is not None
        self.set_acting_email(self._admin_email)

    def visit_console(self) -> None:
        self._as_admin()
        self.response = self.client().get("/console", headers={"accept": "application/json"})

    def visit_console_unauthenticated(self) -> None:
        self.response = self.client().get("/console")

    def try_open_console(self) -> None:
        # Acts as the current (non-admin) user — no admin re-targeting.
        self.response = self.client().get("/console")

    def assert_console_not_found(self) -> None:
        assert self.response is not None
        assert self.response.status_code == 404, f"Expected 404, got {self.response.status_code}"

    # ── overviews ──────────────────────────────────────────────────────────────
    def _console_overview(self, key: str) -> dict:
        assert self.response is not None
        assert self.response.status_code == 200, (
            f"GET /console: {self.response.status_code} {self.response.text}"
        )
        overviews = {o["key"]: o for o in self.response.json()["overviews"]}
        assert key in overviews, f"overview {key!r} not in {list(overviews)}"
        return overviews[key]

    def assert_console_overview_visible(self, key: str) -> None:
        self._console_overview(key)

    def assert_console_overview_shows(self, key: str, text: str) -> None:
        lines = self._console_overview(key)["lines"]
        assert any(text in line for line in lines), f"{text!r} not in {lines}"

    # ── settings ───────────────────────────────────────────────────────────────
    def open_console_settings(self, app: str) -> None:
        self._as_admin()
        self.settings_response = self.client().get(
            f"/console/{app}", headers={"accept": "application/json"}
        )

    def set_console_setting(self, app: str, key: str, value: str) -> None:
        self._as_admin()
        self.settings_response = self.client().put(
            f"/console/{app}/settings/{key}",
            json={"value": value},
            headers={"accept": "application/json"},
        )

    def try_set_console_setting(self, app: str, key: str, value: str) -> None:
        self.response = self.client().put(f"/console/{app}/settings/{key}", json={"value": value})

    def assert_console_setting_shown(self, app: str, key: str, value: str) -> None:
        assert self.settings_response is not None
        assert self.settings_response.status_code == 200, (
            f"GET settings: {self.settings_response.status_code} {self.settings_response.text}"
        )
        body = self.settings_response.json()
        assert body["app"] == app, f"expected settings for {app!r}, got {body['app']!r}"
        settings = {s["key"]: s for s in body["settings"]}
        assert key in settings, f"setting {key!r} not in {list(settings)}"
        actual = str(settings[key]["value"])
        assert actual == value, f"setting {key!r}: expected {value!r}, got {actual!r}"
