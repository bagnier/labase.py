from app.shared.config import get_settings
from tests.e2e.drivers.protocols import BrowserProtocol

_PASSWORD = "Secret1!"


class OrgBrowserMixin(BrowserProtocol):
    def _admin_headers(self) -> dict:
        s = get_settings()
        return {
            "apikey": s.supabase_service_role_key,
            "Authorization": f"Bearer {s.supabase_service_role_key}",
        }

    def _acting_context(self):  # type: ignore[return]
        """Return the active context: secondary if sign_in_as_member was called, else primary."""
        acting_email = getattr(self, "_acting_as_email", None)
        if acting_email:
            return self._secondary_context_for(acting_email)
        return self._context

    def _secondary_context_for(self, email: str):  # type: ignore[return]
        assert self._context
        if not hasattr(self, "_secondary_browser_contexts"):
            self._secondary_browser_contexts: dict = {}
        if email not in self._secondary_browser_contexts:
            ctx = self._context.browser.new_context()
            ctx.request.post(
                f"{self._base_url}/auth/register",
                form={"email": email, "password": _PASSWORD},
            )
            ctx.request.post(
                f"{self._base_url}/auth/login",
                form={"email": email, "password": _PASSWORD},
            )
            self._secondary_browser_contexts[email] = ctx
        return self._secondary_browser_contexts[email]

    def _get_user_id(self, email: str) -> str:
        assert self._context
        s = get_settings()
        resp = self._context.request.get(
            f"{s.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        users = resp.json().get("users", [])
        matched = [u for u in users if u.get("email") == email]
        assert matched, f"User {email!r} not found in Supabase"
        return matched[0]["id"]

    def _get_active_org_id(self, ctx=None) -> str:
        c = ctx or self._acting_context()
        resp = c.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200 and resp.json(), "Cannot resolve active org id"
        orgs = resp.json()
        active_slug = getattr(self, "_active_org_slug", "")
        org = (
            next((o for o in orgs if o.get("slug") == active_slug), orgs[0])
            if active_slug
            else orgs[0]
        )
        return org["id"]

    def _memberships_for(self, email: str) -> list[dict]:
        assert self._context
        s = get_settings()
        resp = self._context.request.get(
            f"{s.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        users = resp.json().get("users", [])
        matched = [u for u in users if u.get("email") == email]
        assert matched, f"User {email!r} not found"
        user_id = matched[0]["id"]
        m_resp = self._context.request.get(
            f"{s.supabase_url}/rest/v1/memberships",
            params={"auth_user_id": f"eq.{user_id}"},
            headers=self._admin_headers(),
        )
        assert m_resp.status == 200
        return m_resp.json()

    # ── basic org assertions ──────────────────────────────────────────────────

    def assert_org_count(self, count: int) -> None:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        assert email, "No registered email stored"
        memberships = self._memberships_for(email)
        assert len(memberships) == count, (
            f"Expected {count} org(s), got {len(memberships)}: {memberships}"
        )

    def assert_is_owner(self) -> None:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        assert email, "No registered email stored"
        memberships = self._memberships_for(email)
        assert memberships, "No memberships found"
        assert memberships[0]["role"] == "owner", (
            f"Expected role=owner, got {memberships[0].get('role')!r}"
        )

    def view_org_list_as(self, email: str) -> None:
        ctx = self._secondary_context_for(email)
        resp = ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200
        self._org_list_response = resp.json()  # type: ignore[attr-defined]

    def assert_other_org_absent(self, email: str) -> None:
        org_list = getattr(self, "_org_list_response", None)
        assert org_list is not None, "Call view_org_list_as first"
        names = [o["name"] for o in org_list]
        ctx = self._secondary_context_for(email)
        resp = ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        other_names = [o["name"] for o in resp.json()]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        assert self._context
        s = get_settings()
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        owner_ctx = self._context.browser.new_context()
        owner_ctx.request.post(
            f"{self._base_url}/auth/register",
            form={"email": owner_email, "password": _PASSWORD},
        )
        owner_ctx.request.post(
            f"{self._base_url}/auth/login",
            form={"email": owner_email, "password": _PASSWORD},
        )
        resp = owner_ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200 and resp.json()
        new_org_id = resp.json()[0]["id"]
        owner_ctx.request.patch(
            f"{self._base_url}/organizations/{new_org_id}",
            data={"name": org_name},
        )
        # Ensure the member user exists
        self._secondary_context_for(email)
        member_user_id = self._get_user_id(email)
        pg_resp = self._context.request.post(
            f"{s.supabase_url}/rest/v1/memberships",
            data={"org_id": new_org_id, "auth_user_id": member_user_id, "role": "member"},
            headers={
                **self._admin_headers(),
                "Prefer": "return=minimal",
            },
        )
        assert pg_resp.status in (200, 201), f"membership insert failed: {pg_resp.text()}"

    def view_org_list(self) -> None:
        resp = self._acting_context().request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200
        self._org_list_response = resp.json()  # type: ignore[attr-defined]

    def assert_org_in_list(self, org_name: str) -> None:
        org_list = getattr(self, "_org_list_response", None)
        if org_list is None:
            resp = self._acting_context().request.get(
                f"{self._base_url}/organizations",
                headers={"accept": "application/json"},
            )
            org_list = resp.json()
        names = [o["name"] for o in org_list]
        assert org_name in names, f"Expected {org_name!r} in org list: {names}"

    def assert_org_absent(self, org_name: str) -> None:
        resp = self._acting_context().request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        names = [o["name"] for o in resp.json()]
        assert org_name not in names, f"{org_name!r} should be absent but found in: {names}"

    def rename_org(self, new_name: str) -> None:
        ctx = self._acting_context()
        resp = ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200 and resp.json()
        active_slug = getattr(self, "_active_org_slug", "")
        orgs = resp.json()
        org = (
            next((o for o in orgs if o.get("slug") == active_slug), orgs[0])
            if active_slug
            else orgs[0]
        )
        rename_resp = ctx.request.patch(
            f"{self._base_url}/organizations/{org['id']}",
            data={"name": new_name},
        )
        self._last_response = rename_resp  # type: ignore[attr-defined]

    def sign_in_as_member(self, email: str) -> None:
        if not getattr(self, "_primary_context_backup", None):
            self._primary_context_backup = self._context  # type: ignore[attr-defined]
        self._acting_as_email = email  # type: ignore[attr-defined]
        self._secondary_context_for(email)

    def assert_action_forbidden(self) -> None:
        last = getattr(self, "_last_response", None)
        assert last is not None, "No response stored"
        status = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status == 403, f"Expected 403, got {status}"

    def view_member_list(self) -> None:
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.get(
            f"{self._base_url}/organizations/{org_id}/members",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200, f"GET members returned {resp.status}"
        self._member_list_response = resp.json()  # type: ignore[attr-defined]

    def assert_member_with_role(self, email: str, role: str) -> None:
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.get(
            f"{self._base_url}/organizations/{org_id}/members",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200
        members = resp.json()
        found = next((m for m in members if m["email"] == email), None)
        assert found is not None, (
            f"{email!r} not found in member list: {[m['email'] for m in members]}"
        )
        assert found["role"] == role, f"Expected role={role!r} for {email!r}, got {found['role']!r}"

    def assert_member_absent(self, email: str) -> None:
        primary_ctx = getattr(self, "_primary_context_backup", None) or self._context
        org_id = self._get_active_org_id(primary_ctx)
        resp = primary_ctx.request.get(
            f"{self._base_url}/organizations/{org_id}/members",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200
        emails = [m["email"] for m in resp.json()]
        assert email not in emails, f"{email!r} should be absent but found: {emails}"

    def set_member_role(self, email: str, role: str) -> None:
        org_id = self._get_active_org_id()
        user_id = self._get_user_id(email)
        self._last_response = self._acting_context().request.patch(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/{user_id}",
            data={"role": role},
        )

    def remove_member(self, email: str) -> None:
        org_id = self._get_active_org_id()
        user_id = self._get_user_id(email)
        self._last_response = self._acting_context().request.delete(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/{user_id}",
            headers={"accept": "application/json"},
        )

    def leave_org(self) -> None:
        org_id = self._get_active_org_id()
        self._last_response = self._acting_context().request.delete(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/me",
            headers={"accept": "application/json"},
        )

    def assert_workspace_card(self, org_name: str) -> None:
        self._p.goto(f"{self._base_url}/dashboard", wait_until="load")
        assert self._p.query_selector(f'[data-workspace-card="{org_name}"]') is not None, (
            f"Workspace card for {org_name!r} not found on dashboard"
        )

    def invite_member(self, email: str, role: str) -> None:
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.post(
            f"{self._base_url}/organizations/{org_id}/invitations",
            data={"email": email},
        )
        self._last_response = resp  # type: ignore[attr-defined]
        if resp.status == 201:
            inv = resp.json()
            self._last_invitation_token = inv.get("token")  # type: ignore[attr-defined]
            self._last_invitation_email = email  # type: ignore[attr-defined]

    def _fetch_pending_invitations(self) -> list[dict]:
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.get(
            f"{self._base_url}/organizations/{org_id}/invitations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200, f"GET invitations returned {resp.status}"
        return resp.json()

    def view_pending_invitations(self) -> None:
        self._pending_invitations = self._fetch_pending_invitations()  # type: ignore[attr-defined]

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
        org_id = self._get_active_org_id()
        invitations = self._fetch_pending_invitations()
        inv = next((i for i in invitations if i["email"] == email), None)
        assert inv is not None, f"No pending invitation for {email!r}"
        self._last_response = self._acting_context().request.delete(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/invitations/{inv['id']}",
            headers={"accept": "application/json"},
        )

    def accept_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        ctx = self._secondary_context_for(email)
        resp = ctx.request.post(
            f"{self._base_url}/invitations/{token}/accept",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200, f"accept invitation returned {resp.status}: {resp.text()}"
        self._last_response = resp  # type: ignore[attr-defined]
        self._last_accept_response = resp.json()  # type: ignore[attr-defined]

    def try_accept_revoked_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        ctx = self._secondary_context_for(email)
        self._last_response = ctx.request.post(  # type: ignore[attr-defined]
            f"{self._base_url}/invitations/{token}/accept",
            headers={"accept": "application/json"},
        )

    def follow_invitation_link_again(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        ctx = self._secondary_context_for(email)
        resp = ctx.request.post(
            f"{self._base_url}/invitations/{token}/accept",
            headers={"accept": "application/json"},
        )
        self._last_response = resp  # type: ignore[attr-defined]
        self._last_accept_response = resp.json() if resp.status == 200 else None  # type: ignore[attr-defined]

    def assert_redirected_to_org_dashboard(self) -> None:
        last = getattr(self, "_last_response", None)
        assert last is not None
        status = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status == 200, f"Expected 200, got {status}"
        data = last.json()
        assert "redirect" in data and "/dashboard" in data["redirect"], (
            f"Expected redirect to dashboard, got: {data}"
        )

    def assert_action_fails_with(self, message: str) -> None:
        last = getattr(self, "_last_response", None)
        assert last is not None, "No response stored"
        status = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status in (400, 409, 404, 422), f"Expected error status, got {status}"
        body = last.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"
