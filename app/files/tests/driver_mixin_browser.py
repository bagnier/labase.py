from app.auth.tests.admin_helpers import delete_user_if_exists, find_users
from app.organizations.tests.admin_helpers import add_membership, set_membership_role
from tests.e2e.drivers.protocols import BrowserProtocol

_PASSWORD = "Secret1!"


class OrgFileBrowserMixin(BrowserProtocol):
    _share_link_url: str | None

    def _files_url(self, slug: str | None = None) -> str:
        s = slug or getattr(self, "_active_org_slug", "")
        return f"{self._base_url}/{s}/files"

    def _goto_files(self) -> None:
        self._p.goto(self._files_url(), wait_until="load")

    def _dom_file_rows(self) -> list:
        return self._p.locator("#file-list > div[data-file-id]").all()

    def _dom_file_names(self) -> list[str]:
        return [row.locator("a").inner_text().strip() for row in self._dom_file_rows()]

    def _dom_find_file_id(self, filename: str) -> str | None:
        for row in self._dom_file_rows():
            if row.locator("a").inner_text().strip() == filename:
                return row.get_attribute("data-file-id") or None
        return None

    def _dom_file_id_by_name(self, filename: str) -> str:
        fid = self._dom_find_file_id(filename)
        if fid is None:
            raise AssertionError(f"File '{filename}' not found in DOM")
        return fid

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

    def _get_primary_org_id(self) -> str:
        assert self._context
        resp = self._context.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200 and resp.json(), "Cannot find primary org"
        return resp.json()[0]["id"]

    # ── basic file ops ────────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        assert self._context
        self._context.request.post(
            self._files_url(),
            multipart={
                "file": {
                    "name": filename,
                    "mimeType": "application/octet-stream",
                    "buffer": content,
                }
            },
        )

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def upload_oversized_file(self, size_mb: int) -> None:
        assert self._context
        content = b"\x00" * (size_mb * 1024 * 1024)
        self._last_response = self._context.request.post(
            self._files_url(),
            multipart={
                "file": {
                    "name": "big.bin",
                    "mimeType": "application/octet-stream",
                    "buffer": content,
                }
            },
        )

    def view_file_list(self) -> None:
        self._goto_files()

    def download_file(self, filename: str) -> None:
        self._goto_files()
        assert self._context
        file_id = self._dom_file_id_by_name(filename)
        self._last_response = self._context.request.get(
            f"{self._files_url()}/{file_id}/download",
        )

    def _api_file_id(self, filename: str) -> str | None:
        assert self._context
        resp = self._context.request.get(self._files_url(), headers={"accept": "application/json"})
        if resp.status != 200:
            return None
        for f in resp.json():
            if f["filename"] == filename:
                return f["id"]
        return None

    def delete_file(self, filename: str) -> None:
        file_id = self._api_file_id(filename)
        if file_id is None:
            self.delete_todo(filename)
            return
        assert self._context
        self._last_response = self._context.request.delete(
            f"{self._files_url()}/{file_id}",
            headers={"accept": "application/json"},
        )

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        file_id = self._api_file_id(old_filename)
        if file_id is None:
            self.rename_todo(old_filename, new_filename)
            return
        assert self._context
        self._last_response = self._context.request.patch(
            f"{self._files_url()}/{file_id}",
            data={"filename": new_filename},
            headers={"accept": "application/json"},
        )

    # ── sign-in with org naming ───────────────────────────────────────────────

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        assert self._context
        delete_user_if_exists(email)
        self._context.request.post(
            f"{self._base_url}/auth/register",
            form={"email": email, "password": _PASSWORD},
        )
        self.sign_in(email, _PASSWORD)  # type: ignore[attr-defined]
        resp = self._context.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        if resp.status == 200:
            orgs = resp.json()
            if orgs:
                org_id = orgs[0]["id"]
                self._context.request.patch(
                    f"{self._base_url}/organizations/{org_id}",
                    data={"name": org_name},
                )
                resp2 = self._context.request.get(
                    f"{self._base_url}/organizations",
                    headers={"accept": "application/json"},
                )
                self._active_org_slug = resp2.json()[0]["slug"]  # type: ignore[attr-defined]
        self._primary_email = email  # type: ignore[attr-defined]
        self._last_registered_email = email

    # ── multi-user operations ─────────────────────────────────────────────────

    def add_member_to_org(self, email: str) -> None:
        assert self._context
        self._secondary_context_for(email)
        add_membership(self._get_primary_org_id(), self._get_user_id(email))
        if not hasattr(self, "_secondary_slugs"):
            self._secondary_slugs: dict = {}
        self._secondary_slugs[email] = getattr(self, "_active_org_slug", "")

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        ctx = self._secondary_context_for(email)
        slug = getattr(self, "_secondary_slugs", {}).get(
            email, getattr(self, "_active_org_slug", "")
        )
        content = b"x" * (size_kb * 1024) if size_kb else b"dummy content"
        ctx.request.post(
            f"{self._base_url}/{slug}/files",
            multipart={
                "file": {
                    "name": filename,
                    "mimeType": "application/octet-stream",
                    "buffer": content,
                }
            },
        )

    def create_user_in_org(self, email: str, org_name: str) -> None:
        ctx = self._secondary_context_for(email)
        resp = ctx.request.get(
            f"{self._base_url}/organizations",
            headers={"accept": "application/json"},
        )
        if resp.status == 200 and resp.json():
            org_id = resp.json()[0]["id"]
            slug = resp.json()[0]["slug"]
            if not hasattr(self, "_secondary_slugs"):
                self._secondary_slugs = {}
            self._secondary_slugs[email] = slug
            ctx.request.patch(
                f"{self._base_url}/organizations/{org_id}",
                data={"name": org_name},
                headers={"content-type": "application/json"},
            )

    def promote_to_owner(self) -> None:
        primary_email = getattr(self, "_primary_email", "")
        set_membership_role(self._get_primary_org_id(), self._get_user_id(primary_email), "owner")

    def demote_to_member(self) -> None:
        primary_email = getattr(self, "_primary_email", "")
        set_membership_role(self._get_primary_org_id(), self._get_user_id(primary_email), "member")

    def generate_share_link(self, filename: str) -> None:
        assert self._context
        self._goto_files()
        file_id = self._dom_file_id_by_name(filename)
        resp = self._context.request.post(
            f"{self._files_url()}/{file_id}/share",
            headers={"accept": "application/json"},
        )
        assert resp.status == 200, f"share link generation failed: {resp.text()}"
        self._share_link_url = resp.json()["url"]  # type: ignore[attr-defined]

    def view_file_list_as(self, email: str) -> None:
        ctx = self._secondary_context_for(email)
        slug = getattr(self, "_secondary_slugs", {}).get(
            email, getattr(self, "_active_org_slug", "")
        )
        resp = ctx.request.get(
            f"{self._base_url}/{slug}/files",
            headers={"accept": "application/json"},
        )
        self._last_response = resp
        self._last_file_list = resp.json() if resp.status == 200 else []  # type: ignore[attr-defined]

    def access_share_link_as(self, email: str) -> None:
        ctx = self._secondary_context_for(email)
        share_url = getattr(self, "_share_link_url", None)
        assert share_url, "No share link stored"
        self._last_response = ctx.request.get(f"{self._base_url}{share_url}")

    def access_share_link_unauthenticated(self) -> None:
        assert self._context
        share_url = getattr(self, "_share_link_url", None)
        assert share_url, "No share link stored"
        anon_ctx = self._context.browser.new_context()
        self._last_response = anon_ctx.request.get(f"{self._base_url}{share_url}")

    # ── assertions ────────────────────────────────────────────────────────────

    def _current_file_names(self) -> list[str]:
        last_list = getattr(self, "_last_file_list", None)
        if last_list is not None:
            self._last_file_list = None  # type: ignore[attr-defined]
            return [f["filename"] for f in last_list]
        self._goto_files()
        return self._dom_file_names()

    def assert_file_visible(self, filename: str) -> None:
        names = self._current_file_names()
        assert filename in names, f"'{filename}' not found in file list: {names}"

    def assert_file_absent(self, filename: str) -> None:
        names = self._current_file_names()
        assert filename not in names, (
            f"'{filename}' should be absent but found in file list: {names}"
        )

    def assert_download_succeeds(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status in (200, 302), (
            f"Expected 200 or 302, got {self._last_response.status}"
        )

    def assert_action_denied(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status == 403, f"Expected 403, got {self._last_response.status}"

    def assert_action_rejected(self) -> None:
        assert self._last_response is not None
        assert self._last_response.status in (413, 422), (
            f"Expected 413 or 422, got {self._last_response.status}"
        )

    def upload_file_with_raw_filename(self, filename: str) -> None:
        assert self._context
        self._last_response = self._context.request.post(
            self._files_url(),
            multipart={
                "file": {
                    "name": filename,
                    "mimeType": "application/octet-stream",
                    "buffer": b"content",
                }
            },
        )

    def assert_upload_rejected(self, status: int) -> None:
        assert self._last_response is not None
        assert self._last_response.status == status, (
            f"Expected {status}, got {self._last_response.status}: {self._last_response.text()}"
        )

    def assert_file_metadata(self, filename: str, size: str, email: str, date: str) -> None:
        self._goto_files()
        for row in self._dom_file_rows():
            if row.locator("a").inner_text().strip() == filename:
                meta = row.locator(".file-meta").inner_text()
                assert email in meta, f"Expected {email!r} in metadata, got: {meta!r}"
                if size.endswith(" KB"):
                    assert size in meta, f"Expected {size!r} in metadata, got: {meta!r}"
                # Date check skipped: set_current_date can't override live server clock
                return
        raise AssertionError(f"File '{filename}' not found in DOM")
