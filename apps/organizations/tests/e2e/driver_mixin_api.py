from apps.auth.tests.given_helpers import user_id_for_email
from apps.shared.settings import get_settings
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.api_base import ApiBase

_PASSWORD = "Secret1!"


class OrgApiMixin(ApiBase):
    _org_list_response: list[dict] | None = None

    def reset_session(self) -> None:
        self._org_list_response = None
        get_settings("organizations")._raw = {}  # restore declared defaults between scenarios
        super().reset_session()

    def _fetch_org_list(self) -> list[dict]:
        resp = self.client().get("/organizations")
        assert resp.status_code == 200, (
            f"GET /organizations returned {resp.status_code}: {resp.text}"
        )
        return resp.json()

    def _orgs_for_current_user(self) -> list[dict]:
        email = getattr(self, "last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        if email:
            resp = self.client_for(email).get("/organizations")
            assert resp.status_code == 200, (
                f"GET /organizations returned {resp.status_code}: {resp.text}"
            )
            return resp.json()
        return self._fetch_org_list()

    def assert_org_count(self, count: int) -> None:
        orgs = self._orgs_for_current_user()
        assert len(orgs) == count, f"Expected {count} org(s), got {len(orgs)}: {orgs}"

    def assert_is_owner(self) -> None:
        orgs = self._orgs_for_current_user()
        assert orgs, "No organisations found"
        assert orgs[0]["role"] == "owner", f"Expected role=owner, got {orgs[0].get('role')!r}"

    def view_org_list_as(self, email: str) -> None:
        resp = self.client_for(email).get("/organizations")
        assert resp.status_code == 200
        self._org_list_response = resp.json()

    def assert_other_org_absent(self, email: str) -> None:
        assert self._org_list_response is not None, "Call view_org_list_as first"
        names = [o["name"] for o in self._org_list_response]
        other_names = [o["name"] for o in self.client_for(email).get("/organizations").json()]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        owner = self.client_for(owner_email)

        orgs = owner.get("/organizations").json()
        assert orgs, f"No org found for {owner_email}"
        handle = orgs[0]["handle"]

        owner.patch(f"/{handle}", json={"name": org_name})

        inv = owner.post(f"/{handle}/invitations", json={"email": email})
        assert inv.status_code == 201, f"Invitation failed: {inv.text}"
        token = inv.json()["token"]

        member = self.client_for(email)
        acc = member.post(f"/invitations/{token}/accept")
        assert acc.status_code == 200, f"Accept invitation failed: {acc.text}"

    def view_org_list(self) -> None:
        resp = self.client().get("/organizations")
        assert resp.status_code == 200
        self._org_list_response = resp.json()

    def assert_org_in_list(self, org_name: str) -> None:
        orgs = (
            self._org_list_response
            if self._org_list_response is not None
            else self._fetch_org_list()
        )
        names = [o["name"] for o in orgs]
        assert org_name in names, f"Expected {org_name!r} in org list: {names}"

    def assert_org_absent(self, org_name: str) -> None:
        orgs = self._fetch_org_list()
        names = [o["name"] for o in orgs]
        assert org_name not in names, f"{org_name!r} should be absent but found in: {names}"

    def rename_org(self, new_name: str) -> None:
        self.response = self.client().patch(f"/{self._handle()}", json={"name": new_name})

    def try_create_org(self, name: str) -> None:
        self.response = self.client().post("/organizations", json={"name": name})

    def sign_in_as_member(self, email: str) -> None:
        self.set_acting_email(email)

    def _handle(self) -> str:
        slug = getattr(self, "active_org_handle", "")
        assert slug, "No active org handle"
        return slug

    def view_member_list(self) -> None:
        self.response = self.client().get(f"/{self._handle()}/members")
        assert self.response.status_code == 200, (
            f"GET /{self._handle()}/members returned"
            f" {self.response.status_code}: {self.response.text}"
        )
        self._member_list_response = self.response.json()

    def assert_member_with_role(self, email: str, role: str) -> None:
        resp = self.client().get(f"/{self._handle()}/members")
        assert resp.status_code == 200, f"GET members returned {resp.status_code}: {resp.text}"
        members = resp.json()
        found = next((m for m in members if m["email"] == email), None)
        assert found is not None, (
            f"{email!r} not found in member list: {[m['email'] for m in members]}"
        )
        assert found["role"] == role, f"Expected role={role!r} for {email!r}, got {found['role']!r}"

    def assert_member_absent(self, email: str) -> None:
        # Use primary client (owner) if current client may have lost org access (e.g. after leave)
        primary = getattr(self, "primary_email", None)
        client = self.client_for(primary) if primary else self.client()
        resp = client.get(f"/{self._handle()}/members")
        assert resp.status_code == 200, (
            f"GET /{self._handle()}/members returned {resp.status_code}: {resp.text}"
        )
        emails = [m["email"] for m in resp.json()]
        assert email not in emails, f"{email!r} should be absent but found in member list: {emails}"

    def set_member_role(self, email: str, role: str) -> None:
        user_id = user_id_for_email(email)
        self.response = self.client().patch(
            f"/{self._handle()}/members/{user_id}", json={"role": role}
        )

    def remove_member(self, email: str) -> None:
        user_id = user_id_for_email(email)
        self.response = self.client().delete(f"/{self._handle()}/members/{user_id}")

    def leave_org(self) -> None:
        self.response = self.client().delete(f"/{self._handle()}/members/me")
        if self.response.status_code not in (204, 403):
            raise AssertionError(
                f"leave_org DELETE /{self._handle()}/members/me returned "
                f"{self.response.status_code}: {self.response.text}"
            )

    def assert_workspace_card(self, org_name: str) -> None:
        names = [o["name"] for o in self._fetch_org_list()]
        assert org_name in names, (
            f"Organisation {org_name!r} not found in the user's org list: {names}"
        )

    def _fetch_pending_invitations(self) -> list[dict]:
        resp = self.client().get(f"/{self._handle()}/invitations")
        assert resp.status_code == 200, f"GET invitations returned {resp.status_code}: {resp.text}"
        return resp.json()

    def invite_member(self, email: str, role: str) -> None:
        self.response = self.client().post(f"/{self._handle()}/invitations", json={"email": email})
        if self.response.status_code == 201:
            inv = self.response.json()
            self._last_invitation_token = inv.get("token")
            self._last_invitation_email = email

    def assert_invitation_email_delivered(self, email: str) -> None:
        self.drain_task_queue()  # the mail is outboxed; deliver it before polling the catcher
        mailbox.assert_invitation_delivered(email, getattr(self, "_last_invitation_token", None))

    def view_pending_invitations(self) -> None:
        self._pending_invitations = self._fetch_pending_invitations()

    def assert_invitation_pending(self, email: str, role: str) -> None:
        invitations = (
            getattr(self, "_pending_invitations", None) or self._fetch_pending_invitations()
        )
        found = next((i for i in invitations if i["email"] == email), None)
        assert found is not None, f"No pending invitation for {email!r}: {invitations}"
        assert found["role"] == role, f"Expected role={role!r}, got {found['role']!r}"
        assert found["status"] == "pending", f"Expected status=pending, got {found['status']!r}"

    def assert_invitation_absent(self, email: str) -> None:
        invitations = self._fetch_pending_invitations()
        emails = [i["email"] for i in invitations]
        assert email not in emails, f"{email!r} should be absent from invitations: {emails}"

    def revoke_invitation(self, email: str) -> None:
        invitations = self._fetch_pending_invitations()
        inv = next((i for i in invitations if i["email"] == email), None)
        assert inv is not None, f"No pending invitation for {email!r} to revoke"
        self.response = self.client().delete(f"/{self._handle()}/invitations/{inv['id']}")

    def register_via_invitation_and_accept(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        client = self._make_client()
        next_url = f"/invitations/{token}"
        client.post(
            "/auth/register", data={"email": email, "password": _PASSWORD, "next": next_url}
        )
        client.post("/auth/login", data={"email": email, "password": _PASSWORD, "next": next_url})
        resp = client.post(f"/invitations/{token}/accept")
        assert resp.status_code == 200, (
            f"POST /invitations/{token}/accept returned {resp.status_code}: {resp.text}"
        )
        self._clients[email] = client
        self._track_auth_email(email)
        self.response = resp

    def accept_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored — call invite_member first"
        self.response = self.client_for(email).post(f"/invitations/{token}/accept")
        assert self.response.status_code == 200, (
            f"POST /invitations/{token}/accept returned"
            f" {self.response.status_code}: {self.response.text}"
        )
        self._last_accept_response = self.response.json()

    def try_accept_revoked_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        self.response = self.client_for(email).post(f"/invitations/{token}/accept")

    def follow_invitation_link_again(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        self.response = self.client_for(email).post(f"/invitations/{token}/accept")
        self._last_accept_response = (
            self.response.json() if self.response.status_code == 200 else None
        )

    def assert_redirected_to_org_dashboard(self) -> None:
        assert self.response.status_code == 200, (
            f"Expected 200 with redirect payload,"
            f" got {self.response.status_code}: {self.response.text}"
        )
        data = self.response.json()
        assert "redirect" in data, f"Expected a redirect, got: {data}"
        assert "/dashboard" in data["redirect"], f"Expected redirect to dashboard, got: {data}"

    def assert_action_fails_with(self, message: str) -> None:
        assert self.response.status_code in (400, 409, 404, 422), (
            f"Expected error status, got {self.response.status_code}: {self.response.text}"
        )
        body = self.response.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "active_org_handle", "")
        self.response = self.client().get(f"/{slug}/dashboard")

    def assert_org_dashboard_visible(self) -> None:
        assert self.response.status_code == 200, (
            f"Expected 200 for org dashboard, got {self.response.status_code}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self.response = self.client().get("/any-org/dashboard")

    # ── Dashboard overviews (verified via the REST JSON endpoint) ────────────────
    def _overview(self, key: str) -> dict:
        slug = getattr(self, "active_org_handle", "")
        resp = self.client().get(f"/{slug}/dashboard/overviews.json")
        assert resp.status_code == 200, (
            f"GET overviews.json returned {resp.status_code}: {resp.text}"
        )
        for ov in resp.json():
            if ov["key"] == key:
                return ov
        raise AssertionError(f"Overview {key!r} not found in {[o['key'] for o in resp.json()]}")

    def assert_overview_visible(self, key: str) -> None:
        self._overview(key)

    def assert_overview_shows(self, key: str, text: str) -> None:
        lines = self._overview(key)["data"].get("lines", [])
        assert any(text in line for line in lines), f"{text!r} not in {key} lines {lines}"

    def assert_overview_lists(self, key: str, text: str) -> None:
        recent = self._overview(key)["data"].get("recent", [])
        assert any(text in item for item in recent), f"{text!r} not in {key} recent {recent}"
