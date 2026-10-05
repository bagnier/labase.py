import uuid
from typing import TYPE_CHECKING

from playwright.sync_api import BrowserContext, Page

from apps.auth.tests.given_helpers import find_users
from tests.e2e.drivers import mailbox
from tests.e2e.drivers.browser_base import _PASSWORD, _VISITOR, BrowserBase


class OrgBrowserMixin(BrowserBase):
    if TYPE_CHECKING:
        # Provided by the auth mixin.
        def sign_in(self, email: str, password: str) -> None: ...

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
        super().reset_session()

    def _read_org_cards_from_profile(self, page: Page) -> list[dict]:
        # Reloaded: a membership or deletion since the render is what these readers look for.
        self.reach_profile(page, fresh=True)
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
        return self._read_org_cards_from_profile(self.page_for(email))

    def _active_slug(self) -> str:
        if self.active_org_handle:
            return self.active_org_handle
        orgs = self._read_org_cards_from_profile(self.page)
        assert orgs, "No org found on profile page"
        self.active_org_handle = orgs[0]["handle"]
        return self.active_org_handle

    def _walk_to_members(self, slug: str, target: Page) -> None:
        """Dashboard → Members card."""
        self.follow_org_nav(slug, "dashboard", target)
        with target.expect_navigation(wait_until="load"):
            target.locator(f"a[href='/{slug}/members']").first.click()

    def _goto_members(self, page: Page | None = None, handle: str | None = None) -> Page:
        """The member list freshly rendered, never a swap's leftover: its controls decide the
        driver's next branch."""
        target = page if page is not None else self.page
        slug = handle or self._active_slug()
        self.be_on(
            f"/{slug}/members", lambda: self._walk_to_members(slug, target), fresh=True, page=target
        )
        return target

    def _user_id_for(self, email: str) -> str:
        users = find_users(email)
        assert users, f"User {email!r} not found in Supabase"
        return users[0].id

    def _probe_blocked(self, method: str, path: str, **fetch_kwargs) -> None:
        """The control is hidden; send its request anyway, for assert_forbidden to require the
        server's refusal."""
        self.last_response = self.page.request.fetch(
            f"{self.base_url}{path}", method=method, **fetch_kwargs
        )

    # ── basic org assertions ──────────────────────────────────────────────────

    def assert_org_count(self, count: int) -> None:
        orgs = self._read_org_cards_from_profile(self.page)
        assert len(orgs) == count, f"Expected {count} org(s), got {len(orgs)}: {orgs}"

    def assert_is_owner(self) -> None:
        email = getattr(self, "last_registered_email", None)
        assert email, "No registered email stored"
        page = self._goto_members()
        el = page.query_selector(f"[data-member-email='{email}'][data-member-role='owner']")
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
        owner = f"owner-{slug}@example.com"
        self.context_for(owner)
        owner_page = self.page_for(owner)
        handle = self._own_org_handle(owner_page, slug)
        self._rename_org(owner_page, handle, org_name)
        token = self._invite_and_read_token(owner_page, handle, email)
        self._accept_invitation_as(email, token)

    def _own_org_handle(self, owner_page: Page, slug: str) -> str:
        orgs = self._read_org_cards_from_profile(owner_page)
        assert orgs, f"No org for the owner of {slug!r}"
        return orgs[0]["handle"]

    def _rename_org(self, owner_page: Page, handle: str, org_name: str) -> None:
        self.follow_org_nav(handle, "settings", owner_page)
        save = owner_page.locator("form:has(input[name=name])").get_by_role("button", name="Save")
        self.submit_labelled_form(
            owner_page,
            {"Organisation name": org_name},
            save,
            method="PATCH",
            path_token=f"/{handle}",
        )

    def _invite_and_read_token(self, owner_page: Page, handle: str, email: str) -> str:
        self._goto_members(owner_page, handle)
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
        return link.rsplit("/", 1)[-1]

    def _accept_invitation_as(self, email: str, token: str) -> None:
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

    def assert_org_absent_for(self, email: str, org_name: str) -> None:
        """Seen by a named observer: the actor may have deleted their own account."""
        names = [o["name"] for o in self._fetch_orgs_for(email)]
        assert org_name not in names, f"{org_name!r} should be absent for {email}, got: {names}"

    def rename_org(self, new_name: str) -> None:
        slug = self._active_slug()
        # A member has no way in: the server must refuse the form's request.
        if self.page.locator(f"aside a[href='/{slug}/settings']").count() == 0:
            self._probe_blocked("PATCH", f"/{slug}", form={"name": new_name})
            return
        self.follow_org_nav(slug, "settings")
        save = self.page.locator("form:has(input[name=name])").get_by_role("button", name="Save")
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Organisation name": new_name},
            save,
            method="PATCH",
            path_token=f"/{slug}",
        )

    def try_create_org(self, name: str) -> None:
        # Sent directly, so the server enforces the owned-org limit.
        self.last_response = self.page.request.fetch(
            f"{self.base_url}/organizations", method="POST", form={"name": name}
        )

    def sign_in_as_member(self, email: str) -> None:
        self.set_acting_email(email)
        self.context_for(email)

    def view_member_list(self) -> None:
        self._goto_members()

    def _the_member_list(self):
        """Read as the owner: a member who just left would get a 403."""
        owner = getattr(self, "primary_email", "")
        if owner:
            self.set_acting_email(owner)
        return self._goto_members()

    def assert_member_with_role(self, email: str, role: str) -> None:
        page = self._the_member_list()
        selector = f"[data-member-email='{email}'][data-member-role='{role}']"
        el = page.query_selector(selector)
        member_list = page.query_selector("#member-list")
        member_html = page.inner_html("#member-list") if member_list else page.content()[:500]
        assert el is not None, (
            f"Member {email!r} with role {role!r} not found on members page. HTML: {member_html}"
        )

    def assert_member_absent(self, email: str) -> None:
        page = self._the_member_list()
        el = page.query_selector(f"[data-member-email='{email}']")
        assert el is None, f"{email!r} should be absent from members page but was found"

    def set_member_role(self, email: str, role: str) -> None:
        page = self._goto_members()
        action = "[data-promote]" if role == "owner" else "[data-demote]"
        # Absent on one's own row: probe the API so the server must refuse.
        if page.query_selector(f"[data-member-email='{email}'] {action}") is None:
            self._probe_blocked(
                "PATCH",
                f"/{self._active_slug()}/members/{self._user_id_for(email)}",
                form={"role": role},
            )
            return
        page.click(f"[data-member-email='{email}'] [data-manage]")
        self.last_response = self.click_and_capture(
            page, f"[data-member-email='{email}'] {action}", "PATCH", "/members/"
        )

    def remove_member(self, email: str) -> None:
        page = self._goto_members()
        # Absent on one's own row: probe the API so the last-owner guard must refuse.
        if page.query_selector(f"[data-member-email='{email}'] [data-remove]") is None:
            self._probe_blocked(
                "DELETE", f"/{self._active_slug()}/members/{self._user_id_for(email)}"
            )
            return
        page.click(f"[data-member-email='{email}'] [data-manage]")
        self.last_response = self.click_and_capture(
            page, f"[data-member-email='{email}'] [data-remove]", "DELETE", "/members/"
        )

    def leave_org(self) -> None:
        page = self._goto_members()
        # Leave is in the row's Manage menu.
        manage = page.query_selector("li:has([data-leave]) [data-manage]")
        if manage is None:
            self._probe_blocked("DELETE", f"/{self._active_slug()}/members/me")
            return
        manage.click()
        self.last_response = self.click_and_capture(page, "[data-leave]", "DELETE", "/members/me")
        if self.last_response.status < 400:
            page.wait_for_load_state("load")

    def assert_workspace_card(self, org_name: str) -> None:
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
        self.drain_task_queue()  # deliver the queued mail
        mailbox.assert_invitation_delivered(email, self._last_invitation_token)

    def _fetch_pending_invitations(self) -> list[dict]:
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
            # Any id will do: the owner gate answers 403 before the id is looked up.
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
        self._follow_accept_to_registration(page, token)
        self._register(page, email)
        self._sign_in_on_this_page(page, email)
        self._click_accept_back_on_the_invitation(page)
        self._become(email, visitor_ctx, page)
        self._last_accept_response = {"redirect": page.url}

    def _follow_accept_to_registration(self, page: Page, token: str) -> None:
        page.goto(f"{self.base_url}/invitations/{token}", wait_until="load")
        page.click("[data-accept]")  # → /auth/register?next=…
        page.wait_for_load_state("load")

    def _register(self, page: Page, email: str) -> None:
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_PASSWORD)
        page.get_by_role("button", name="Create my account").click()
        page.wait_for_load_state("load")

    def _sign_in_on_this_page(self, page: Page, email: str) -> None:
        """Sign in from the login page registration lands on, ``next`` kept."""
        page.get_by_label("Email").fill(email)
        page.get_by_label("Password").fill(_PASSWORD)
        page.get_by_role("button", name="Sign in").click()
        page.wait_for_load_state("load")

    def _click_accept_back_on_the_invitation(self, page: Page) -> None:
        accept_btn = page.query_selector("[data-accept]")
        assert accept_btn is not None, (
            f"Accept button not found after register+login redirect — landed on {page.url}"
        )
        page.click("[data-accept]")
        page.wait_for_load_state("load")

    def _become(self, email: str, ctx: BrowserContext, page: Page) -> None:
        self._contexts[email] = ctx
        self._pages[email] = page

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
        assert page.query_selector("[data-accept]") is None, (
            "Accepted invitation should not expose an accept button"
        )
        assert page.query_selector("[data-error]") is not None, (
            "Expected the already-accepted acknowledgement on the page"
        )
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
            assert "redirect" in data, f"Expected a redirect, got: {data}"
            assert "/dashboard" in data["redirect"], (
                f"Expected redirect to /<slug>/dashboard, got: {data}"
            )

    def assert_action_fails_with(self, message: str) -> None:
        # A revoked or used link renders an error page without the accept button.
        if self._invitation_action_failed:
            self._invitation_action_failed = False
            return
        # Errors come back as a fragment (200 with [data-error]).
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
        self.last_response = self.follow_org_nav(self.active_org_handle, "dashboard")

    def assert_org_dashboard_visible(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 200, (
            f"Expected 200 for org dashboard, got {self.last_response.status}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self.last_response = self.page.goto(f"{self.base_url}/any-org/dashboard", wait_until="load")

    # ── Dashboard overviews (rendered) ───────────────────────────────────────────
    def _overview_text(self, key: str) -> str:
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

    def assert_overview_does_not_list(self, key: str, text: str) -> None:
        content = self._overview_text(key)
        assert text not in content, f"{text!r} unexpectedly listed in {key} overview: {content!r}"
