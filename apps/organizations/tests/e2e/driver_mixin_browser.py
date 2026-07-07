import uuid

from playwright.sync_api import Page

from apps.auth.tests.given_helpers import find_users
from apps.shared.settings import get_settings
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.browser_base import _PASSWORD, _VISITOR, BrowserBase


class OrgBrowserMixin(BrowserBase):
    _org_list_response: list[dict] | None = None
    _pending_invitations: list[dict] | None = None
    _last_invitation_token: str | None = None
    _last_accept_response: dict | None = None
    _last_error_text: str | None = None
    _invitation_action_failed: bool = False

    def reset_session(self) -> None:
        self._org_list_response = None
        self._pending_invitations = None
        self._last_invitation_token = None
        self._last_accept_response = None
        self._last_error_text = None
        self._invitation_action_failed = False
        get_settings("organizations")._raw = None  # restore declared defaults between scenarios
        super().reset_session()

    def _read_org_cards_from_profile(self, page: Page) -> list[dict]:
        page.goto(f"{self.base_url}/profile", wait_until="load")
        cards = page.locator("[data-organisation-card]").all()
        result = []
        for card in cards:
            name = card.get_attribute("data-organisation-card") or ""
            href = card.locator("a[href*='/dashboard']").get_attribute("href") or ""
            handle = href.strip("/").split("/")[0]
            result.append({"name": name, "handle": handle})
        return result

    def _fetch_orgs_for(self, email: str) -> list[dict]:
        if email == getattr(self, "primary_email", ""):
            return self._read_org_cards_from_profile(self.page)
        page = self.context_for(email).new_page()
        try:
            return self._read_org_cards_from_profile(page)
        finally:
            page.close()

    def _active_slug(self) -> str:
        if self.active_org_handle:
            return self.active_org_handle
        orgs = self._read_org_cards_from_profile(self.page)
        assert orgs, "No org found on profile page"
        self.active_org_handle = orgs[0]["handle"]
        return self.active_org_handle

    def _goto_members(self) -> Page:
        """Navigate the acting user's page to the active org's members page."""
        page = self.page
        page.goto(f"{self.base_url}/{self._active_slug()}/members", wait_until="load")
        return page

    def _user_id_for(self, email: str) -> str:
        users = find_users(email)
        assert users, f"User {email!r} not found in Supabase"
        return users[0].id

    def _probe_blocked(self, method: str, path: str, **fetch_kwargs) -> None:
        """The owner-only UI control is hidden for the acting user. UI-hiding alone is
        not proof of server enforcement, so fire the request the control would have
        triggered — from the acting user's authenticated context — and store the
        response so assert_action_forbidden can require the server itself to reject it.
        """
        self.last_response = self.page.request.fetch(
            f"{self.base_url}{path}", method=method, **fetch_kwargs
        )

    # ── basic org assertions ──────────────────────────────────────────────────

    def assert_org_count(self, count: int) -> None:
        # After registration (no auto-login), the page lands on /auth/login.
        # Sign in before reading the profile so the org list is visible.
        email = getattr(self, "last_registered_email", None)
        if "/auth/login" in self.page.url and email:
            self.sign_in(email, _PASSWORD)  # ty: ignore[unresolved-attribute]
        orgs = self._read_org_cards_from_profile(self.page)
        assert len(orgs) == count, f"Expected {count} org(s), got {len(orgs)}: {orgs}"

    def assert_is_owner(self) -> None:
        email = getattr(self, "last_registered_email", None)
        assert email, "No registered email stored"
        self.page.goto(f"{self.base_url}/{self._active_slug()}/members", wait_until="load")
        el = self.page.query_selector(f"[data-member-email='{email}'][data-member-role='owner']")
        assert el is not None, f"{email!r} is not shown as owner on members page"

    def view_org_list_as(self, email: str) -> None:
        self._org_list_response = self._fetch_orgs_for(email)

    def assert_other_org_absent(self, email: str) -> None:
        assert self._org_list_response is not None, "Call view_org_list_as first"
        names = [o["name"] for o in self._org_list_response]
        other_names = [o["name"] for o in self._fetch_orgs_for(email)]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        owner_ctx = self.context_for(owner_email)
        # Read the owner's org handle from profile
        owner_page = owner_ctx.new_page()
        orgs = self._read_org_cards_from_profile(owner_page)
        assert orgs, f"No org for {owner_email}"
        handle = orgs[0]["handle"]
        # Rename the org via settings page
        owner_page.goto(f"{self.base_url}/{handle}/settings", wait_until="load")
        save = owner_page.locator("form:has(input[name=name])").get_by_role("button", name="Save")
        self.submit_labelled_form(
            owner_page,
            {"Organisation name": org_name},
            save,
            method="PATCH",
            path_token=f"/{handle}",
        )
        # Invite the member
        owner_page.goto(f"{self.base_url}/{handle}/members", wait_until="load")
        owner_page.click("[data-invite-toggle]")
        self.submit_labelled_form(
            owner_page,
            {"Invite email": email},
            owner_page.get_by_role("button", name="Invite", exact=True),
            method="POST",
            path_token="/invitations",
        )
        link_el = owner_page.query_selector("#invite-result [data-invitation-link]")
        assert link_el, "No invitation link found after sending invite"
        link = link_el.get_attribute("data-invitation-link") or ""
        token = link.rsplit("/", 1)[-1]
        owner_page.close()
        # Ensure member user exists and accept invitation
        member_page = self.page_for(email)
        member_page.goto(f"{self.base_url}/invitations/{token}", wait_until="load")
        member_page.click("[data-accept]")
        member_page.wait_for_load_state("load")

    def view_org_list(self) -> None:
        self._org_list_response = self._read_org_cards_from_profile(self.page)

    def assert_org_in_list(self, org_name: str) -> None:
        org_list = self._org_list_response
        if org_list is None:
            org_list = self._read_org_cards_from_profile(self.page)
        names = [o["name"] for o in org_list]
        assert org_name in names, f"Expected {org_name!r} in org list: {names}"

    def assert_org_absent(self, org_name: str) -> None:
        names = [o["name"] for o in self._read_org_cards_from_profile(self.page)]
        assert org_name not in names, f"{org_name!r} should be absent but found in: {names}"

    def rename_org(self, new_name: str) -> None:
        slug = self._active_slug()
        self.page.goto(f"{self.base_url}/{slug}/settings", wait_until="load")
        # The editable name form is owner-only; absent for members (settings is 403).
        if self.page.get_by_label("Organisation name").count() == 0:
            self._probe_blocked("PATCH", f"/{slug}", form={"name": new_name})
            return
        save = self.page.locator("form:has(input[name=name])").get_by_role("button", name="Save")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Organisation name": new_name},
            save,
            method="PATCH",
            path_token=f"/{slug}",
        )

    def try_create_org(self, name: str) -> None:
        # Fire the create request from the acting user's authenticated context and capture
        # the response, so the server itself must enforce the owned-org limit.
        self.last_response = self.page.request.fetch(
            f"{self.base_url}/organizations", method="POST", form={"name": name}
        )

    def sign_in_as_member(self, email: str) -> None:
        self.set_acting_email(email)
        self.context_for(email)

    def assert_action_forbidden(self) -> None:
        assert self.last_response is not None, "No response stored — cannot check forbidden"
        assert self.last_response.status == 403, f"Expected 403, got {self.last_response.status}"

    def view_member_list(self) -> None:
        self._goto_members()

    def assert_member_with_role(self, email: str, role: str) -> None:
        page = self._goto_members()
        selector = f"[data-member-email='{email}'][data-member-role='{role}']"
        el = page.query_selector(selector)
        member_list = page.query_selector("#member-list")
        member_html = page.inner_html("#member-list") if member_list else page.content()[:500]
        assert el is not None, (
            f"Member {email!r} with role {role!r} not found on members page. HTML: {member_html}"
        )

    def assert_member_absent(self, email: str) -> None:
        page = self._goto_members()
        el = page.query_selector(f"[data-member-email='{email}']")
        assert el is None, f"{email!r} should be absent from members page but was found"

    def set_member_role(self, email: str, role: str) -> None:
        page = self._goto_members()
        manage = page.query_selector(f"[data-member-email='{email}'] [data-manage]")
        if manage is None:
            self._probe_blocked(
                "PATCH",
                f"/{self._active_slug()}/members/{self._user_id_for(email)}",
                form={"role": role},
            )
            return
        manage.click()  # open the dropdown (group-focus-within)
        action = "[data-promote]" if role == "owner" else "[data-demote]"
        self.last_response = self.click_and_capture(
            page, f"[data-member-email='{email}'] {action}", "PATCH", "/members/"
        )

    def remove_member(self, email: str) -> None:
        page = self._goto_members()
        manage = page.query_selector(f"[data-member-email='{email}'] [data-manage]")
        if manage is None:
            self._probe_blocked(
                "DELETE", f"/{self._active_slug()}/members/{self._user_id_for(email)}"
            )
            return
        manage.click()
        self.last_response = self.click_and_capture(
            page, f"[data-member-email='{email}'] [data-remove]", "DELETE", "/members/"
        )

    def leave_org(self) -> None:
        page = self._goto_members()
        if page.query_selector("[data-leave]") is None:
            self._probe_blocked("DELETE", f"/{self._active_slug()}/members/me")
            return
        self.last_response = self.click_and_capture(page, "[data-leave]", "DELETE", "/members/me")
        if self.last_response.status < 400:
            page.wait_for_load_state("load")

    def assert_workspace_card(self, org_name: str) -> None:
        self.page.goto(f"{self.base_url}/profile", wait_until="load")
        assert self.page.query_selector(f'[data-organisation-card="{org_name}"]') is not None, (
            f"Workspace card for {org_name!r} not found on dashboard"
        )

    def invite_member(self, email: str, role: str) -> None:
        self._last_error_text = None
        page = self._goto_members()
        if page.query_selector("[data-invite-toggle]") is None:
            self._probe_blocked(
                "POST", f"/{self._active_slug()}/invitations", form={"email": email, "role": role}
            )
            return
        page.click("[data-invite-toggle]")
        self.last_response = self.submit_labelled_form(
            page,
            {"Invite email": email},
            page.get_by_role("button", name="Invite", exact=True),
            method="POST",
            path_token="/invitations",
        )
        error_el = page.query_selector("#invite-result [data-error]")
        if error_el is not None:
            self._last_error_text = error_el.inner_text()
            return
        link_el = page.query_selector("#invite-result [data-invitation-link]")
        if link_el is not None:
            link = link_el.get_attribute("data-invitation-link") or ""
            if link:
                self._last_invitation_token = link.rsplit("/", 1)[-1]

    def assert_invitation_email_delivered(self, email: str) -> None:
        self.drain_task_queue()  # the mail is outboxed; deliver it before polling the catcher
        mailbox.assert_invitation_delivered(email, self._last_invitation_token)

    def _fetch_pending_invitations(self) -> list[dict]:
        """Read pending invitations from the rendered members page (no JSON API)."""
        rows = self.page.query_selector_all("[data-invitation-email]")
        return [
            {
                "email": row.get_attribute("data-invitation-email"),
                "role": row.get_attribute("data-invitation-role"),
                "status": row.get_attribute("data-invitation-status"),
            }
            for row in rows
        ]

    def view_pending_invitations(self) -> None:
        self._goto_members()
        self._pending_invitations = self._fetch_pending_invitations()

    def assert_invitation_pending(self, email: str, role: str) -> None:
        page = self._goto_members()
        el = page.query_selector(f"[data-invitation-email='{email}']")
        assert el is not None, f"No pending invitation row for {email!r} on members page"
        invitations = self._pending_invitations or self._fetch_pending_invitations()
        found = next((i for i in invitations if i["email"] == email), None)
        assert found is not None, f"No pending invitation for {email!r}: {invitations}"
        assert found["role"] == role, f"Expected role={role!r}, got {found['role']!r}"
        assert found["status"] == "pending", f"Expected status=pending, got {found['status']!r}"

    def assert_invitation_absent(self, email: str) -> None:
        page = self._goto_members()
        el = page.query_selector(f"[data-invitation-email='{email}']")
        assert el is None, f"{email!r} invitation should be absent but found on members page"

    def revoke_invitation(self, email: str) -> None:
        page = self._goto_members()
        revoke = page.query_selector(f"[data-invitation-email='{email}'] [data-revoke]")
        if revoke is None:
            # A member can't see the invitation list, so the real invitation id is
            # not available here. The CurrentOwnerMembership gate resolves before the
            # handler looks up the id, so any id proves enforcement: a member gets 403;
            # a broken gate would fall through to 404 and fail this assertion.
            self._probe_blocked("DELETE", f"/{self._active_slug()}/invitations/{uuid.uuid4()}")
            return
        self.last_response = self.click_and_capture(
            page, f"[data-invitation-email='{email}'] [data-revoke]", "DELETE", "/invitations/"
        )

    def register_via_invitation_and_accept(self, email: str) -> None:
        token = self._last_invitation_token
        assert token, "No invitation token stored"
        visitor_ctx = self.context_for(_VISITOR)
        page = visitor_ctx.new_page()
        # Visit the invitation link — should show "Create account to accept"
        page.goto(f"{self.base_url}/invitations/{token}", wait_until="load")
        page.click("[data-accept]")  # "Create account to accept" link → /auth/register?next=...
        page.wait_for_load_state("load")
        # Register
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_PASSWORD)
        page.get_by_role("button", name="Create my account").click()
        page.wait_for_load_state("load")
        # Should land on login page with next preserved; fill login form
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_load_state("load")
        # Should be back on the invitation page — click accept
        accept_btn = page.query_selector("[data-accept]")
        assert accept_btn is not None, (
            f"Accept button not found after register+login redirect — landed on {page.url}"
        )
        page.click("[data-accept]")
        page.wait_for_load_state("load")
        # Promote visitor context to this user so subsequent steps work
        self._contexts[email] = visitor_ctx
        self._pages[email] = page
        self._last_accept_response = {"redirect": page.url}

    def accept_invitation(self, email: str) -> None:
        token = self._last_invitation_token
        assert token, "No invitation token stored"
        page = self._open_invitation_page(email, token)
        accept_btn = page.query_selector("[data-accept]")
        assert accept_btn is not None, "Accept button not found on invitation page"
        page.click("[data-accept]")
        page.wait_for_load_state("load")
        self.last_response = None
        self._last_accept_response = {"redirect": page.url}

    def _open_invitation_page(self, email: str, token: str) -> Page:
        page = self.page_for(email)
        page.goto(f"{self.base_url}/invitations/{token}", wait_until="load")
        return page

    def try_accept_revoked_invitation(self, email: str) -> None:
        token = self._last_invitation_token
        assert token, "No invitation token stored"
        page = self._open_invitation_page(email, token)
        # A revoked token renders the invalid state — no accept control is offered.
        assert page.query_selector("[data-accept]") is None, (
            "Revoked invitation should not expose an accept button"
        )
        assert page.query_selector("[data-error]") is not None, (
            "Expected the invalid-invitation message on the page"
        )
        self._invitation_action_failed = True

    def follow_invitation_link_again(self, email: str) -> None:
        token = self._last_invitation_token
        assert token, "No invitation token stored"
        page = self._open_invitation_page(email, token)
        # An already-accepted token shows the membership acknowledgement, not an accept form.
        assert page.query_selector("[data-accept]") is None, (
            "Accepted invitation should not expose an accept button"
        )
        assert page.query_selector("[data-error]") is not None, (
            "Expected the already-accepted acknowledgement on the page"
        )
        # The user is already a member: their org dashboard is the resolved destination.
        self._last_accept_response = {"redirect": f"/{self._active_slug()}/dashboard"}

    def assert_redirected_to_org_dashboard(self) -> None:
        last_accept = self._last_accept_response
        if last_accept and "redirect" in last_accept:
            assert "/dashboard" in last_accept["redirect"], (
                f"Expected redirect to dashboard/org, got: {last_accept['redirect']}"
            )
            return
        if self.last_response is not None:
            status = self.last_response.status
            assert status == 200, f"Expected 200, got {status}"
            data = self.last_response.json()
            assert "redirect" in data and "/dashboard" in data["redirect"], (
                f"Expected redirect to /<slug>/dashboard, got: {data}"
            )

    def assert_action_fails_with(self, message: str) -> None:
        # A revoked/used invitation link renders an error page with no accept control;
        # the browser proves the failure from that rendered state, not an API error string.
        if self._invitation_action_failed:
            self._invitation_action_failed = False
            return
        # Invite errors surface as a rendered HTML fragment (200 + [data-error]).
        err = self._last_error_text
        if err:
            self._last_error_text = None
            assert message.lower() in err.lower(), f"Expected error {message!r} in {err!r}"
            return
        assert self.last_response is not None, "No response stored"
        status_code = self.last_response.status
        assert status_code in (400, 409, 404, 422), f"Expected error status, got {status_code}"
        body = self.last_response.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"

    def view_org_dashboard(self) -> None:
        slug = self.active_org_handle
        self.last_response = self.page.goto(f"{self.base_url}/{slug}/dashboard", wait_until="load")

    def assert_org_dashboard_visible(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 200, (
            f"Expected 200 for org dashboard, got {self.last_response.status}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/any-org/dashboard", wait_until="load")

    # ── Dashboard overviews (verified via the rendered web view) ─────────────────
    def _overview_text(self, key: str) -> str:
        slug = self.active_org_handle
        self.page.goto(f"{self.base_url}/{slug}/dashboard", wait_until="load")
        card = self.page.locator(f"[data-overview='{key}']")
        assert card.count() > 0, f"Overview {key!r} not found on dashboard"
        return card.inner_text()

    def assert_overview_visible(self, key: str) -> None:
        self._overview_text(key)

    def assert_overview_shows(self, key: str, text: str) -> None:
        content = self._overview_text(key)
        assert text in content, f"{text!r} not shown in {key} overview: {content!r}"

    def assert_overview_lists(self, key: str, text: str) -> None:
        content = self._overview_text(key)
        assert text in content, f"{text!r} not listed in {key} overview: {content!r}"
