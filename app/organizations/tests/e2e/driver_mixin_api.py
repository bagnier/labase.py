from tests.e2e.drivers.api_base import ApiBase

_PASSWORD = "Secret1!"


class OrgApiMixin(ApiBase):
    _org_list_response: list[dict] | None = None

    def _fetch_org_list(self) -> list[dict]:
        resp = self.json_client("GET", "/organizations")
        assert resp.status_code == 200, (
            f"GET /organizations returned {resp.status_code}: {resp.text}"
        )
        return resp.json()

    def _orgs_for_current_user(self) -> list[dict]:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        if email:
            client = self._client_for(email)
            resp = self.json_client("GET", "/organizations", client)
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
        client = self._client_for(email)
        resp = self.json_client("GET", "/organizations", client)
        assert resp.status_code == 200
        self._org_list_response = resp.json()

    def assert_other_org_absent(self, email: str) -> None:
        assert self._org_list_response is not None, "Call view_org_list_as first"
        names = [o["name"] for o in self._org_list_response]
        client = self._client_for(email)
        resp = self.json_client("GET", "/organizations", client)
        other_names = [o["name"] for o in resp.json()]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        owner = self._make_client_for(owner_email)

        orgs = self.json_client("GET", "/organizations", owner).json()
        assert orgs, f"No org found for {owner_email}"
        handle = orgs[0]["handle"]

        self.json_client("PATCH", f"/{handle}", owner, json={"name": org_name})

        inv = self.json_client("POST", f"/{handle}/invitations", owner, json={"email": email})
        assert inv.status_code == 201, f"Invitation failed: {inv.text}"
        token = inv.json()["token"]

        member = self._client_for(email)
        acc = self.json_client("POST", f"/invitations/{token}/accept", member)
        assert acc.status_code == 200, f"Accept invitation failed: {acc.text}"

    def view_org_list(self) -> None:
        resp = self.json_client("GET", "/organizations")
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
        self._response = self.json_client("PATCH", f"/{self._handle()}", json={"name": new_name})

    def sign_in_as_member(self, email: str) -> None:
        if not getattr(self, "_primary_client_backup", None):
            self._primary_client_backup = self._client  # type: ignore[attr-defined]
        client = self._client_for(email)
        self._client = client  # type: ignore[assignment]

    def assert_action_forbidden(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 403, (
            f"Expected 403, got {self._response.status_code}: {self._response.text}"
        )

    def _handle(self) -> str:
        slug = getattr(self, "_active_org_handle", "")
        assert slug, "No active org handle"
        return slug

    def _user_id_for(self, email: str) -> str:
        return self._user_id_for_email(email)

    def view_member_list(self) -> None:
        self._response = self.json_client("GET", f"/{self._handle()}/members")
        assert self._response.status_code == 200, (
            f"GET /{self._handle()}/members returned"
            f" {self._response.status_code}: {self._response.text}"
        )
        self._member_list_response = self._response.json()

    def assert_member_with_role(self, email: str, role: str) -> None:
        resp = self.json_client("GET", f"/{self._handle()}/members")
        assert resp.status_code == 200, f"GET members returned {resp.status_code}: {resp.text}"
        members = resp.json()
        found = next((m for m in members if m["email"] == email), None)
        assert found is not None, (
            f"{email!r} not found in member list: {[m['email'] for m in members]}"
        )
        assert found["role"] == role, f"Expected role={role!r} for {email!r}, got {found['role']!r}"

    def assert_member_absent(self, email: str) -> None:
        # Use primary client (owner) if current client may have lost org access (e.g. after leave)
        client = getattr(self, "_primary_client_backup", None) or self.client
        resp = self.json_client("GET", f"/{self._handle()}/members", client)
        assert resp.status_code == 200, (
            f"GET /{self._handle()}/members returned {resp.status_code}: {resp.text}"
        )
        emails = [m["email"] for m in resp.json()]
        assert email not in emails, f"{email!r} should be absent but found in member list: {emails}"

    def set_member_role(self, email: str, role: str) -> None:
        user_id = self._user_id_for(email)
        self._response = self.json_client(
            "PATCH", f"/{self._handle()}/members/{user_id}", json={"role": role}
        )

    def remove_member(self, email: str) -> None:
        user_id = self._user_id_for(email)
        self._response = self.json_client("DELETE", f"/{self._handle()}/members/{user_id}")

    def leave_org(self) -> None:
        self._response = self.json_client("DELETE", f"/{self._handle()}/members/me")
        if self._response.status_code not in (204, 403):
            raise AssertionError(
                f"leave_org DELETE /{self._handle()}/members/me returned "
                f"{self._response.status_code}: {self._response.text}"
            )

    def assert_workspace_card(self, org_name: str) -> None:
        names = [o["name"] for o in self._fetch_org_list()]
        assert org_name in names, (
            f"Organisation {org_name!r} not found in the user's org list: {names}"
        )

    def _fetch_pending_invitations(self) -> list[dict]:
        resp = self.json_client("GET", f"/{self._handle()}/invitations")
        assert resp.status_code == 200, f"GET invitations returned {resp.status_code}: {resp.text}"
        return resp.json()

    def invite_member(self, email: str, role: str) -> None:
        self._response = self.json_client(
            "POST", f"/{self._handle()}/invitations", json={"email": email}
        )
        if self._response.status_code == 201:
            inv = self._response.json()
            self._last_invitation_token = inv.get("token")
            self._last_invitation_email = email

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
        self._response = self.json_client("DELETE", f"/{self._handle()}/invitations/{inv['id']}")

    def accept_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored — call invite_member first"
        client = self._client_for(email)
        self._response = self.json_client("POST", f"/invitations/{token}/accept", client)
        assert self._response.status_code == 200, (
            f"POST /invitations/{token}/accept returned"
            f" {self._response.status_code}: {self._response.text}"
        )
        self._last_accept_response = self._response.json()

    def try_accept_revoked_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        client = self._client_for(email)
        self._response = self.json_client("POST", f"/invitations/{token}/accept", client)

    def follow_invitation_link_again(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        client = self._client_for(email)
        self._response = self.json_client("POST", f"/invitations/{token}/accept", client)
        self._last_accept_response = (
            self._response.json() if self._response.status_code == 200 else None
        )

    def assert_redirected_to_org_dashboard(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, (
            f"Expected 200 with redirect payload,"
            f" got {self._response.status_code}: {self._response.text}"
        )
        data = self._response.json()
        assert "redirect" in data and "/dashboard" in data["redirect"], (
            f"Expected redirect to dashboard, got: {data}"
        )

    def assert_action_fails_with(self, message: str) -> None:
        assert self._response is not None, "No response stored"
        assert self._response.status_code in (400, 409, 404, 422), (
            f"Expected error status, got {self._response.status_code}: {self._response.text}"
        )
        body = self._response.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "_active_org_handle", "")
        self._response = self.run(self.client.get(f"/{slug}/dashboard"))

    def assert_org_dashboard_visible(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, (
            f"Expected 200 for org dashboard, got {self._response.status_code}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self._response = self.run(self.client.get("/any-org/dashboard"))
