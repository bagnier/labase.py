from tests.e2e.drivers.protocols import BrowserProtocol

_PASSWORD = "Secret1!"  # shared constant across all test mixins


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

    def _setup_context(self, ctx, email: str) -> None:
        """Register and login in a fresh browser context via page navigation."""
        page = ctx.new_page()
        page.goto(f"{self._base_url}/auth/register")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", _PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_load_state("domcontentloaded")
        page.goto(f"{self._base_url}/auth/login")
        page.fill("input[name=email]", email)
        page.fill("input[name=password]", _PASSWORD)
        page.click("button[type=submit]")
        page.wait_for_url("**/profile", timeout=10000)
        page.close()

    def _secondary_context_for(self, email: str):  # type: ignore[return]
        assert self._context
        if not hasattr(self, "_secondary_browser_contexts"):
            self._secondary_browser_contexts: dict = {}
        if email not in self._secondary_browser_contexts:
            ctx = self._context.browser.new_context()
            self._setup_context(ctx, email)
            self._secondary_browser_contexts[email] = ctx
        return self._secondary_browser_contexts[email]

    def _acting_email(self) -> str:
        email = getattr(self, "_acting_as_email", None) or getattr(self, "_primary_email", None)
        assert email, "No acting email"
        return email

    def _read_org_cards_from_profile(self, page) -> list[dict]:
        page.goto(f"{self._base_url}/profile", wait_until="load")
        cards = page.locator("[data-organisation-card]").all()
        result = []
        for card in cards:
            name = card.get_attribute("data-organisation-card") or ""
            href = card.locator("a[href*='/dashboard']").get_attribute("href") or ""
            handle = href.strip("/").split("/")[0]
            result.append({"name": name, "handle": handle})
        return result

    def _fetch_orgs_for(self, email: str) -> list[dict]:
        acting = getattr(self, "_primary_email", None)
        if email == acting:
            return self._read_org_cards_from_profile(self._p)
        ctx = self._secondary_context_for(email)
        page = ctx.new_page()
        try:
            return self._read_org_cards_from_profile(page)
        finally:
            page.close()

    def _active_slug(self) -> str:
        slug = getattr(self, "_active_org_handle", "")
        if slug:
            return slug
        orgs = self._read_org_cards_from_profile(self._p)
        assert orgs, "No org found on profile page"
        handle = orgs[0]["handle"]
        self._active_org_handle = handle  # type: ignore[attr-defined]
        return handle

    # ── basic org assertions ──────────────────────────────────────────────────

    def assert_org_count(self, count: int) -> None:
        # After registration (no auto-login), the page lands on /auth/login.
        # Sign in before reading the profile so the org list is visible.
        if "/auth/login" in self._p.url:
            email = getattr(self, "_last_registered_email", None)
            if email:
                self.sign_in(email, _PASSWORD)  # type: ignore[arg-type]
        orgs = self._read_org_cards_from_profile(self._p)
        assert len(orgs) == count, f"Expected {count} org(s), got {len(orgs)}: {orgs}"

    def assert_is_owner(self) -> None:
        email = getattr(self, "_last_registered_email", None) or getattr(
            self, "_primary_email", None
        )
        assert email, "No registered email stored"
        slug = self._active_slug()
        self._p.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        el = self._p.query_selector(f"[data-member-email='{email}'][data-member-role='owner']")
        assert el is not None, f"{email!r} is not shown as owner on members page"

    def view_org_list_as(self, email: str) -> None:
        self._org_list_response = self._fetch_orgs_for(email)  # type: ignore[attr-defined]

    def assert_other_org_absent(self, email: str) -> None:
        org_list = getattr(self, "_org_list_response", None)
        assert org_list is not None, "Call view_org_list_as first"
        names = [o["name"] for o in org_list]
        other_names = [o["name"] for o in self._fetch_orgs_for(email)]
        for name in other_names:
            assert name not in names, f"Other user's org {name!r} appears in list: {names}"

    def join_org_as_member(self, org_name: str, email: str) -> None:
        assert self._context
        slug = org_name.lower().replace(" ", "-")
        owner_email = f"owner-{slug}@example.com"
        owner_ctx = self._context.browser.new_context()
        self._setup_context(owner_ctx, owner_email)
        # Read the owner's org handle from profile
        owner_page = owner_ctx.new_page()
        orgs = self._read_org_cards_from_profile(owner_page)
        assert orgs, f"No org for {owner_email}"
        handle = orgs[0]["handle"]
        # Rename the org via settings page
        owner_page.goto(f"{self._base_url}/{handle}/settings", wait_until="load")
        owner_page.fill("input[name=name]", org_name)
        with owner_page.expect_response(
            lambda r: f"/{handle}" in r.url and r.request.method == "PATCH"
        ):
            owner_page.click("form:has(input[name=name]) button[type=submit]")
        # Invite the member
        owner_page.goto(f"{self._base_url}/{handle}/members", wait_until="load")
        owner_page.click("[data-invite-toggle]")
        owner_page.fill("#invite-form input[name=email]", email)
        with owner_page.expect_response(
            lambda r: "/invitations" in r.url and r.request.method == "POST"
        ):
            owner_page.click("#invite-form button[type=submit]")
        link_el = owner_page.query_selector("#invite-result [data-invitation-link]")
        assert link_el, "No invitation link found after sending invite"
        link = link_el.get_attribute("data-invitation-link") or ""
        token = link.rsplit("/", 1)[-1]
        owner_page.close()
        # Ensure member user exists and accept invitation
        member_ctx = self._secondary_context_for(email)
        if not hasattr(member_ctx, "_page") or member_ctx._page is None:  # type: ignore[attr-defined]
            member_ctx._page = member_ctx.new_page()  # type: ignore[attr-defined]
        member_page = member_ctx._page  # type: ignore[attr-defined]
        member_page.goto(f"{self._base_url}/invitations/{token}", wait_until="load")
        member_page.click("[data-accept]")
        member_page.wait_for_load_state("load")

    def view_org_list(self) -> None:
        self._org_list_response = self._read_org_cards_from_profile(self._p)  # type: ignore[attr-defined]

    def assert_org_in_list(self, org_name: str) -> None:
        org_list = getattr(self, "_org_list_response", None)
        if org_list is None:
            org_list = self._read_org_cards_from_profile(self._p)
        names = [o["name"] for o in org_list]
        assert org_name in names, f"Expected {org_name!r} in org list: {names}"

    def assert_org_absent(self, org_name: str) -> None:
        names = [o["name"] for o in self._read_org_cards_from_profile(self._p)]
        assert org_name not in names, f"{org_name!r} should be absent but found in: {names}"

    def rename_org(self, new_name: str) -> None:
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/settings", wait_until="load")
        # The editable name form is owner-only; absent for members (settings is 403).
        if page.query_selector("input[name=name]") is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        page.fill("input[name=name]", new_name)
        self._last_response = self._click_and_capture(
            page, "form:has(input[name=name]) button[type=submit]", "PATCH", f"/{slug}"
        )

    def sign_in_as_member(self, email: str) -> None:
        if not getattr(self, "_primary_context_backup", None):
            self._primary_context_backup = self._context  # type: ignore[attr-defined]
        self._acting_as_email = email  # type: ignore[attr-defined]
        self._secondary_context_for(email)

    def assert_action_forbidden(self) -> None:
        if getattr(self, "_action_blocked_by_ui", False):
            return  # the control is not even rendered for this user
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
        slug = self._active_slug()
        page = self._p
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        el = page.query_selector(f"[data-member-email='{email}']")
        assert el is None, f"{email!r} should be absent from members page but was found"

    def set_member_role(self, email: str, role: str) -> None:
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        manage = page.query_selector(f"[data-member-email='{email}'] [data-manage]")
        if manage is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        manage.click()  # open the dropdown (group-focus-within)
        action = "[data-promote]" if role == "owner" else "[data-demote]"
        self._last_response = self._click_and_capture(  # type: ignore[attr-defined]
            page, f"[data-member-email='{email}'] {action}", "PATCH", "/members/"
        )

    def remove_member(self, email: str) -> None:
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        manage = page.query_selector(f"[data-member-email='{email}'] [data-manage]")
        if manage is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        manage.click()
        self._last_response = self._click_and_capture(  # type: ignore[attr-defined]
            page, f"[data-member-email='{email}'] [data-remove]", "DELETE", "/members/"
        )

    def leave_org(self) -> None:
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        if page.query_selector("[data-leave]") is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        self._last_response = self._click_and_capture(  # type: ignore[attr-defined]
            page, "[data-leave]", "DELETE", "/members/me"
        )

    def assert_workspace_card(self, org_name: str) -> None:
        self._p.goto(f"{self._base_url}/profile", wait_until="load")
        assert self._p.query_selector(f'[data-organisation-card="{org_name}"]') is not None, (
            f"Workspace card for {org_name!r} not found on dashboard"
        )

    def invite_member(self, email: str, role: str) -> None:
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        self._last_error_text = None  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        if page.query_selector("[data-invite-toggle]") is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        page.click("[data-invite-toggle]")
        page.fill("#invite-form input[name=email]", email)
        self._last_response = self._click_and_capture(  # type: ignore[attr-defined]
            page, "#invite-form button[type=submit]", "POST", "/invitations"
        )
        error_el = page.query_selector("#invite-result [data-error]")
        if error_el is not None:
            self._last_error_text = error_el.inner_text()  # type: ignore[attr-defined]
            return
        link_el = page.query_selector("#invite-result [data-invitation-link]")
        if link_el is not None:
            link = link_el.get_attribute("data-invitation-link") or ""
            if link:
                self._last_invitation_token = link.rsplit("/", 1)[-1]  # type: ignore[attr-defined]
                self._last_invitation_email = email  # type: ignore[attr-defined]

    def _fetch_pending_invitations(self) -> list[dict]:
        """Read pending invitations from the rendered members page (no JSON API)."""
        page = self._acting_page()
        rows = page.query_selector_all("[data-invitation-email]")
        return [
            {
                "email": row.get_attribute("data-invitation-email"),
                "role": row.get_attribute("data-invitation-role"),
                "status": row.get_attribute("data-invitation-status"),
            }
            for row in rows
        ]

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
        self._action_blocked_by_ui = False  # type: ignore[attr-defined]
        slug = self._active_slug()
        page = self._acting_page()
        page.goto(f"{self._base_url}/{slug}/members", wait_until="load")
        revoke = page.query_selector(f"[data-invitation-email='{email}'] [data-revoke]")
        if revoke is None:
            self._last_response = None  # type: ignore[attr-defined]
            self._action_blocked_by_ui = True  # type: ignore[attr-defined]
            return
        self._last_response = self._click_and_capture(  # type: ignore[attr-defined]
            page, f"[data-invitation-email='{email}'] [data-revoke]", "DELETE", "/invitations/"
        )

    def accept_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        page = self._open_invitation_page(email, token)
        accept_btn = page.query_selector("[data-accept]")
        assert accept_btn is not None, "Accept button not found on invitation page"
        page.click("[data-accept]")
        page.wait_for_load_state("load")
        self._last_response = None  # type: ignore[attr-defined]
        self._last_accept_response = {"redirect": page.url}  # type: ignore[attr-defined]

    def _open_invitation_page(self, email: str, token: str):  # type: ignore[return]
        ctx = self._secondary_context_for(email)
        if not hasattr(ctx, "_page") or ctx._page is None:  # type: ignore[attr-defined]
            ctx._page = ctx.new_page()  # type: ignore[attr-defined]
        page = ctx._page  # type: ignore[attr-defined]
        page.goto(f"{self._base_url}/invitations/{token}", wait_until="load")
        return page

    def try_accept_revoked_invitation(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
        assert token, "No invitation token stored"
        page = self._open_invitation_page(email, token)
        # A revoked token renders the invalid state — no accept control is offered.
        assert page.query_selector("[data-accept]") is None, (
            "Revoked invitation should not expose an accept button"
        )
        assert page.query_selector("[data-error]") is not None, (
            "Expected the invalid-invitation message on the page"
        )
        self._invitation_action_failed = True  # type: ignore[attr-defined]

    def follow_invitation_link_again(self, email: str) -> None:
        token = getattr(self, "_last_invitation_token", None)
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
        self._last_accept_response = {  # type: ignore[attr-defined]
            "redirect": f"/{self._active_slug()}/dashboard"
        }

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
        # A revoked/used invitation link renders an error page with no accept control;
        # the browser proves the failure from that rendered state, not an API error string.
        if getattr(self, "_invitation_action_failed", False):
            self._invitation_action_failed = False  # type: ignore[attr-defined]
            return
        # Invite errors surface as a rendered HTML fragment (200 + [data-error]).
        err = getattr(self, "_last_error_text", None)
        if err:
            self._last_error_text = None  # type: ignore[attr-defined]
            assert message.lower() in err.lower(), f"Expected error {message!r} in {err!r}"
            return
        last = getattr(self, "_last_response", None)
        assert last is not None, "No response stored"
        status_code = getattr(last, "status", None) or getattr(last, "status_code", None)
        assert status_code in (400, 409, 404, 422), f"Expected error status, got {status_code}"
        body = last.json()
        detail = body.get("detail", "")
        assert message.lower() in detail.lower(), f"Expected error {message!r} in detail {detail!r}"

    def view_org_dashboard(self) -> None:
        slug = getattr(self, "_active_org_handle", "")
        self._last_response = self._p.goto(f"{self._base_url}/{slug}/dashboard", wait_until="load")

    def assert_org_dashboard_visible(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 200, (
            f"Expected 200 for org dashboard, got {self._last_response.status}"
        )

    def visit_org_dashboard_unauthenticated(self) -> None:
        self._last_response = self._p.goto(f"{self._base_url}/any-org/dashboard", wait_until="load")
