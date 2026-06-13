from app.auth.tests.admin_helpers import find_users
from app.organizations.tests.admin_helpers import add_membership, memberships_for_user
from tests.e2e.drivers.protocols import BrowserProtocol

_PASSWORD = "Secret1!"


class OrgBrowserMixin(BrowserProtocol):
    def _acting_context(self):  # type: ignore[return]
        """Return the active context: secondary if sign_in_as_member was called, else primary."""
        acting_email = getattr(self, "_acting_as_email", None)
        if acting_email:
            return self._secondary_context_for(acting_email)
        return self._context

    def _acting_page(self):  # type: ignore[return]
        """Return the Playwright page for the active context."""
        acting_email = getattr(self, "_acting_as_email", None)
        if acting_email:
            ctx = self._secondary_context_for(acting_email)
            if not hasattr(ctx, "_page") or ctx._page is None:  # type: ignore[attr-defined]
                ctx._page = ctx.new_page()  # type: ignore[attr-defined]
            return ctx._page  # type: ignore[attr-defined]
        return self._p

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
        users = find_users(email)
        assert users, f"User {email!r} not found in Supabase"
        return users[0].id

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

    def _active_slug(self) -> str:
        slug = getattr(self, "_active_org_slug", "")
        if slug:
            return slug
        ctx = self._acting_context()
        resp = ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200 and resp.json()
        return resp.json()[0]["slug"]

    def _memberships_for(self, email: str) -> list[dict]:
        return memberships_for_user(self._get_user_id(email))

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
        add_membership(new_org_id, self._get_user_id(email))

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
        # Navigate to settings page to validate the HTML renders
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/settings", wait_until="load")
        # Perform rename via JSON API to keep auth state stable
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.patch(
            f"{self._base_url}/organizations/{org_id}",
            data={"name": new_name},
            headers={"accept": "application/json"},
        )
        self._last_response = resp  # type: ignore[attr-defined]

    def sign_in_as_member(self, email: str) -> None:
        if not getattr(self, "_primary_context_backup", None):
            self._primary_context_backup = self._context  # type: ignore[attr-defined]
        self._acting_as_email = email  # type: ignore[attr-defined]
        self._secondary_context_for(email)

    def assert_action_forbidden(self) -> None:
        last = getattr(self, "_last_response", None)
        assert last is not None, "No response stored — cannot check forbidden"
        status_code = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status_code == 403, f"Expected 403, got {status_code}"

    def view_member_list(self) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")

    def assert_member_with_role(self, email: str, role: str) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        selector = f"[data-member-email='{email}'][data-member-role='{role}']"
        el = page.query_selector(selector)
        member_list = page.query_selector("#member-list")
        member_html = page.inner_html("#member-list") if member_list else page.content()[:500]
        assert el is not None, (
            f"Member {email!r} with role {role!r} not found on members page. HTML: {member_html}"
        )

    def assert_member_absent(self, email: str) -> None:
        primary_ctx = getattr(self, "_primary_context_backup", None) or self._context
        # Get the primary user's active slug
        resp = primary_ctx.request.get(
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
        slug = org["slug"]
        page = self._p
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        el = page.query_selector(f"[data-member-email='{email}']")
        assert el is None, f"{email!r} should be absent from members page but was found"

    def set_member_role(self, email: str, role: str) -> None:
        # Navigate to members page so the HTML renders (validates the UI)
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        # Perform role change via JSON API to capture the response for assert_action_forbidden
        org_id = self._get_active_org_id()
        user_id = self._get_user_id(email)
        self._last_response = self._acting_context().request.patch(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/{user_id}",
            data={"role": role},
            headers={"accept": "application/json"},
        )

    def remove_member(self, email: str) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        row = page.query_selector(f"[data-member-email='{email}']")
        assert row is not None, f"Member row for {email!r} not found"
        # Use API to perform removal and capture response for assert_action_forbidden
        org_id = self._get_active_org_id()
        user_id = self._get_user_id(email)
        self._last_response = self._acting_context().request.delete(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/{user_id}",
            headers={"accept": "application/json"},
        )

    def leave_org(self) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        # Use API for leave so we can capture forbidden responses
        org_id = self._get_active_org_id()
        self._last_response = self._acting_context().request.delete(  # type: ignore[attr-defined]
            f"{self._base_url}/organizations/{org_id}/members/me",
            headers={"accept": "application/json"},
        )

    def assert_workspace_card(self, org_name: str) -> None:
        self._p.goto(f"{self._base_url}/profile", wait_until="load")
        assert self._p.query_selector(f'[data-workspace-card="{org_name}"]') is not None, (
            f"Workspace card for {org_name!r} not found on dashboard"
        )

    def invite_member(self, email: str, role: str) -> None:
        # Navigate to members page to validate the HTML renders
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        # Create invitation via JSON API to capture the response
        org_id = self._get_active_org_id()
        resp = self._acting_context().request.post(
            f"{self._base_url}/organizations/{org_id}/invitations",
            data={"email": email},
            headers={"accept": "application/json"},
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
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        self._pending_invitations = self._fetch_pending_invitations()  # type: ignore[attr-defined]

    def assert_invitation_pending(self, email: str, role: str) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        el = page.query_selector(f"[data-invitation-email='{email}']")
        assert el is not None, f"No pending invitation row for {email!r} on members page"
        invitations = (
            getattr(self, "_pending_invitations", None) or self._fetch_pending_invitations()
        )
        found = next((i for i in invitations if i["email"] == email), None)
        assert found is not None, f"No pending invitation for {email!r}: {invitations}"
        assert found["role"] == role, f"Expected role={role!r}, got {found['role']!r}"
        assert found["status"] == "pending", f"Expected status=pending, got {found['status']!r}"

    def assert_invitation_absent(self, email: str) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        el = page.query_selector(f"[data-invitation-email='{email}']")
        assert el is None, f"{email!r} invitation should be absent but found on members page"

    def revoke_invitation(self, email: str) -> None:
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        inv_row = page.query_selector(f"[data-invitation-email='{email}']")
        assert inv_row is not None, f"No invitation row for {email!r}"
        # Use API for revoke to capture response status
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
        if not hasattr(ctx, "_page") or ctx._page is None:  # type: ignore[attr-defined]
            ctx._page = ctx.new_page()  # type: ignore[attr-defined]
        page = ctx._page  # type: ignore[attr-defined]
        page.goto(f"{self._base_url}/invitations/{token}", wait_until="load")
        accept_btn = page.query_selector("[data-accept]")
        assert accept_btn is not None, "Accept button not found on invitation page"
        page.click("[data-accept]")
        page.wait_for_load_state("load")
        self._last_response = None  # type: ignore[attr-defined]
        self._last_accept_response = {"redirect": page.url}  # type: ignore[attr-defined]

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
        last_accept = getattr(self, "_last_accept_response", None)
        if last_accept and "redirect" in last_accept:
            assert "/dashboard" in last_accept["redirect"], (
                f"Expected redirect to dashboard/org, got: {last_accept['redirect']}"
            )
            return
        last = getattr(self, "_last_response", None)
        if last is not None:
            status_code = getattr(last, "status", None) or getattr(last, "status_code", None)
            assert status_code == 200, f"Expected 200, got {status_code}"
            data = last.json()
            assert "redirect" in data and "/dashboard" in data["redirect"], (
                f"Expected redirect to /<slug>/dashboard, got: {data}"
            )

    def assert_action_fails_with(self, message: str) -> None:
        last = getattr(self, "_last_response", None)
        assert last is not None, "No response stored"
        status_code = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status_code in (400, 409, 404, 422), f"Expected error status, got {status_code}"
        body = last.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "_active_org_slug", "")
        self._last_response = self._p.goto(f"{self._base_url}/{slug}/dashboard", wait_until="load")

    def assert_org_dashboard_visible(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, (
            f"Expected 200 for org dashboard, got {self._last_response.status}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/any-org/dashboard", wait_until="load")
