import httpx

from app.main import app
from app.shared.config import get_settings
from tests.e2e.drivers.protocols import ApiProtocol

_PASSWORD = "Secret1!"


class OrgApiMixin(ApiProtocol):
    _org_list_response: list[dict] | None = None

    def _fetch_org_list(self) -> list[dict]:
        resp = self._run(self._c.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200, (
            f"GET /organizations returned {resp.status_code}: {resp.text}"
        )
        return resp.json()

    def _admin_memberships_for(self, email: str) -> list[dict]:
        """Fetch memberships for email using service role (no user auth needed)."""
        s = get_settings()
        admin_headers = {
            "apikey": s.supabase_service_role_key,
            "Authorization": f"Bearer {s.supabase_service_role_key}",
            "Accept": "application/json",
        }
        users_resp = httpx.get(
            f"{s.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=admin_headers,
        )
        all_users = users_resp.json().get("users", [])
        matched = [u for u in all_users if u.get("email") == email]
        assert matched, f"User {email!r} not found in Supabase"
        user_id = matched[0]["id"]

        memberships_resp = httpx.get(
            f"{s.supabase_url}/rest/v1/memberships",
            params={"auth_user_id": f"eq.{user_id}"},
            headers=admin_headers,
        )
        assert memberships_resp.status_code == 200, (
            f"memberships query failed: {memberships_resp.text}"
        )
        return memberships_resp.json()

    def assert_org_count(self, count: int) -> None:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        assert email, "No registered email stored — cannot assert org count"
        memberships = self._admin_memberships_for(email)
        assert len(memberships) == count, (
            f"Expected {count} org(s), got {len(memberships)}: {memberships}"
        )

    def assert_is_owner(self) -> None:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        assert email, "No registered email stored — cannot assert is_owner"
        memberships = self._admin_memberships_for(email)
        assert memberships, "No memberships found"
        assert memberships[0]["role"] == "owner", (
            f"Expected role=owner, got {memberships[0].get('role')!r}"
        )

    def view_org_list_as(self, email: str) -> None:
        client = self._client_for(email)
        resp = self._run(client.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200
        self._org_list_response = resp.json()

    def assert_other_org_absent(self, email: str) -> None:
        assert self._org_list_response is not None, "Call view_org_list_as first"
        names = [o["name"] for o in self._org_list_response]
        # The other user's org should not appear; we verify by checking no org whose slug
        # is owned by `email` appears — simplest proxy: fetch that user's own org name
        client = self._client_for(email)
        resp = self._run(client.get("/organizations", headers={"accept": "application/json"}))
        other_names = [o["name"] for o in resp.json()]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        s = get_settings()
        admin_headers = {
            "apikey": s.supabase_service_role_key,
            "Authorization": f"Bearer {s.supabase_service_role_key}",
        }
        # Create a throwaway owner for this org (so email can join as member, not owner)
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        transport = httpx.ASGITransport(app=app)
        owner_client = httpx.AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        )
        self._run(
            owner_client.post("/auth/register", data={"email": owner_email, "password": _PASSWORD})
        )
        self._run(
            owner_client.post("/auth/login", data={"email": owner_email, "password": _PASSWORD})
        )
        resp = self._run(owner_client.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200 and resp.json()
        new_org_id = resp.json()[0]["id"]
        self._run(
            owner_client.patch(
                f"/organizations/{new_org_id}",
                json={"name": org_name},
                headers={"accept": "application/json"},
            )
        )

        # Add email as member of this new org
        member_auth_id = self._user_id_for_email(email)
        pg_resp = httpx.post(
            f"{s.supabase_url}/rest/v1/memberships",
            json={"org_id": new_org_id, "auth_user_id": member_auth_id, "role": "member"},
            headers={
                **admin_headers,
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        assert pg_resp.status_code in (200, 201), f"membership insert failed: {pg_resp.text}"

    def view_org_list(self) -> None:
        resp = self._run(self._c.get("/organizations", headers={"accept": "application/json"}))
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
        orgs = self._fetch_org_list()
        assert orgs, "No organisations to rename"
        active_slug = getattr(self, "_active_org_slug", "")
        org = (
            next((o for o in orgs if o.get("slug") == active_slug), orgs[0])
            if active_slug
            else orgs[0]
        )
        org_id = org["id"]
        resp = self._run(
            self._c.patch(
                f"/organizations/{org_id}",
                json={"name": new_name},
                headers={"accept": "application/json"},
            )
        )
        self._response = resp

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

    def _get_active_org_id(self, client=None) -> str:
        import httpx as _httpx

        c: _httpx.AsyncClient = client or self._c
        resp = self._run(c.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200 and resp.json(), "Cannot resolve active org id"
        orgs = resp.json()
        active_slug = getattr(self, "_active_org_slug", "")
        org = (
            next((o for o in orgs if o.get("slug") == active_slug), orgs[0])
            if active_slug
            else orgs[0]
        )
        return org["id"]

    def _user_id_for(self, email: str) -> str:
        return self._user_id_for_email(email)

    def view_member_list(self) -> None:
        org_id = self._get_active_org_id()
        self._response = self._run(
            self._c.get(f"/organizations/{org_id}/members", headers={"accept": "application/json"})
        )
        assert self._response.status_code == 200, (
            f"GET /organizations/{org_id}/members returned {self._response.status_code}: {self._response.text}"
        )
        self._member_list_response = self._response.json()

    def assert_member_with_role(self, email: str, role: str) -> None:
        org_id = self._get_active_org_id()
        resp = self._run(
            self._c.get(f"/organizations/{org_id}/members", headers={"accept": "application/json"})
        )
        assert resp.status_code == 200, f"GET members returned {resp.status_code}: {resp.text}"
        members = resp.json()
        found = next((m for m in members if m["email"] == email), None)
        assert found is not None, (
            f"{email!r} not found in member list: {[m['email'] for m in members]}"
        )
        assert found["role"] == role, f"Expected role={role!r} for {email!r}, got {found['role']!r}"

    def assert_member_absent(self, email: str) -> None:
        # Use primary client (owner) if current client may have lost org access (e.g. after leave)
        client = getattr(self, "_primary_client_backup", None) or self._c
        org_id = self._get_active_org_id(client)
        resp = self._run(
            client.get(f"/organizations/{org_id}/members", headers={"accept": "application/json"})
        )
        assert resp.status_code == 200, (
            f"GET /organizations/{org_id}/members returned {resp.status_code}: {resp.text}"
        )
        emails = [m["email"] for m in resp.json()]
        assert email not in emails, f"{email!r} should be absent but found in member list: {emails}"

    def set_member_role(self, email: str, role: str) -> None:
        org_id = self._get_active_org_id()
        user_id = self._user_id_for(email)
        self._response = self._run(
            self._c.patch(
                f"/organizations/{org_id}/members/{user_id}",
                json={"role": role},
                headers={"accept": "application/json"},
            )
        )

    def remove_member(self, email: str) -> None:
        org_id = self._get_active_org_id()
        user_id = self._user_id_for(email)
        self._response = self._run(
            self._c.delete(
                f"/organizations/{org_id}/members/{user_id}",
                headers={"accept": "application/json"},
            )
        )

    def leave_org(self) -> None:
        org_id = self._get_active_org_id()
        self._response = self._run(
            self._c.delete(
                f"/organizations/{org_id}/members/me",
                headers={"accept": "application/json"},
            )
        )
        if self._response.status_code not in (204, 403):
            raise AssertionError(
                f"leave_org DELETE /organizations/{org_id}/members/me returned "
                f"{self._response.status_code}: {self._response.text}"
            )

    def assert_workspace_card(self, org_name: str) -> None:
        resp = self._run(self._c.get("/dashboard"))
        assert resp.status_code == 200, f"GET /dashboard returned {resp.status_code}"
        assert f'data-workspace-card="{org_name}"' in resp.text, (
            f"Workspace card for {org_name!r} not found in dashboard"
        )
