import httpx

from apps.auth.tests.given_helpers import (
    clear_all_admin_roles,
    create_user,
    delete_user_if_exists,
    set_admin_role,
)
from tests.e2e.drivers.api_base import ApiBase

_ADMIN_PASSWORD = "Test1234!"
_USER_PASSWORD = "Secret1!"


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

    def set_org_override(self, app: str, key: str, value: str) -> None:
        self._as_admin()
        handle = getattr(self, "active_org_handle", "")
        resp = self.client().post(
            f"/console/{app}/org-settings",
            json={"org_handle": handle, "key": key, "value": value},
        )
        assert resp.status_code == 200, f"override failed: {resp.status_code} {resp.text}"

    def assert_org_override_listed(self, app: str, key: str, value: str) -> None:
        self._as_admin()
        resp = self.client().get(f"/console/{app}", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"GET /console/{app}: {resp.status_code}"
        handle = getattr(self, "active_org_handle", "")
        overrides = resp.json()["org_overrides"]
        found = next((o for o in overrides if o["key"] == key and o["handle"] == handle), None)
        assert found is not None, f"no override {key!r} for {handle!r}: {overrides}"
        assert found["value"] == value, f"expected {value!r}, got {found['value']!r}"

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

    def assert_console_supabase_link(self, app: str, fragment: str) -> None:
        assert self.settings_response is not None
        assert self.settings_response.status_code == 200, (
            f"GET settings: {self.settings_response.status_code} {self.settings_response.text}"
        )
        body = self.settings_response.json()
        assert body["app"] == app, f"expected settings for {app!r}, got {body['app']!r}"
        supabase = body.get("supabase")
        assert supabase is not None, f"no Supabase link for {app!r}"
        assert fragment in supabase["href"], f"{fragment!r} not in {supabase['href']!r}"

    # ── server admins ────────────────────────────────────────────────────────────
    def ensure_no_server_admin(self) -> None:
        clear_all_admin_roles()

    def seed_existing_admin(self) -> None:
        # An admin must exist so a later registrant is *not* auto-promoted by the bootstrap.
        # Seeded straight into GoTrue (no session) to leave the acting user untouched.
        email = "seed-admin@example.com"
        delete_user_if_exists(email)
        set_admin_role(create_user(email, _ADMIN_PASSWORD))
        self._track_auth_email(email)

    def _register_and_login(self, email: str, password: str) -> None:
        client = self._make_client()
        client.post("/auth/register", json={"email": email, "password": password})
        client.post("/auth/login", json={"email": email, "password": password})
        self._clients[email] = client
        self._track_auth_email(email)

    def register_and_sign_in(self, email: str) -> None:
        # Registration fires the bootstrap (promotes the first user) *before* this login,
        # so the issued JWT already carries the admin claim where applicable.
        delete_user_if_exists(email)
        self._register_and_login(email, _USER_PASSWORD)
        self.set_acting_email(email)

    def register_regular_user(self, email: str) -> None:
        delete_user_if_exists(email)
        self._register_and_login(email, _USER_PASSWORD)

    def sign_in_again(self, email: str) -> None:
        # A designation only lands in the JWT on a fresh sign-in — mint a new token.
        self._clients.pop(email, None)
        self._register_and_login(email, _USER_PASSWORD)
        self.set_acting_email(email)

    def assert_can_open_console(self, email: str) -> None:
        resp = self.client_for(email).get("/console", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"

    def assert_refused_console(self, email: str) -> None:
        resp = self.client_for(email).get("/console")
        assert resp.status_code == 404, f"Expected 404, got {resp.status_code}"

    def _admins(self) -> list[dict]:
        self._as_admin()
        resp = self.client().get("/console/admins", headers={"accept": "application/json"})
        assert resp.status_code == 200, f"GET /console/admins: {resp.status_code} {resp.text}"
        return resp.json()["admins"]

    def open_admins_page(self) -> None:
        self._admins()

    def assert_admin_list_status(self, email: str, *, is_admin: bool) -> None:
        rows = {a["email"]: a for a in self._admins()}
        assert email in rows, f"{email!r} not in admin list {list(rows)}"
        actual = rows[email]["is_admin"]
        assert actual == is_admin, f"{email!r}: expected is_admin={is_admin}, got {actual}"

    def assert_email_absent_from_admin_list(self, email: str) -> None:
        rows = {a["email"] for a in self._admins()}
        assert email not in rows, f"{email!r} unexpectedly in admin list {sorted(rows)}"

    def add_server_admin_by_email(self, email: str) -> None:
        self._as_admin()
        self.response = self.client().post(
            "/console/admins", json={"email": email}, headers={"accept": "application/json"}
        )

    def assert_admin_add_error(self, email: str) -> None:
        assert self.response is not None
        assert self.response.status_code == 404, (
            f"Expected 404 adding {email!r}, got {self.response.status_code}: {self.response.text}"
        )

    def _put_admin(self, email: str, is_admin: bool) -> httpx.Response:
        return self.client().put(
            f"/console/admins/{email}",
            json={"is_admin": is_admin},
            headers={"accept": "application/json"},
        )

    def designate_server_admin(self, email: str) -> None:
        self._as_admin()
        resp = self._put_admin(email, True)
        assert resp.status_code == 200, f"designate {email!r}: {resp.status_code} {resp.text}"

    def revoke_server_admin(self, email: str) -> None:
        self._as_admin()
        self.response = self._put_admin(email, False)

    def try_designate_server_admin(self, email: str) -> None:
        # Acts as the current (non-admin) user — no admin re-targeting.
        self.response = self.client().put(f"/console/admins/{email}", json={"is_admin": True})
