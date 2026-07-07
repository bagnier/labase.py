import contextlib
import tempfile

from apps.auth.tests.given_helpers import delete_user_if_exists
from apps.shared.settings import get_settings
from tests.e2e.drivers.browser_base import BrowserBase


class OrgFileBrowserMixin(BrowserBase):
    primary_email: str
    active_org_handle: str
    last_registered_email: str | None
    secondary_handles: dict[str, str]
    _share_link_url: str | None

    def reset_session(self) -> None:
        self.primary_email = ""
        self.active_org_handle = ""
        self.last_registered_email = None
        self.secondary_handles = {}
        self._share_link_url = None
        get_settings("files")._raw = None  # restore declared defaults between scenarios
        super().reset_session()

    def _files_url(self, slug: str | None = None) -> str:
        s = slug or self.active_org_handle
        return f"{self.base_url}/{s}/files"

    def _goto_files(self) -> None:
        self.page.goto(self._files_url(), wait_until="load")

    def _dom_file_rows(self) -> list:
        return self.page.locator("#file-list > li[data-file-id]").all()

    def _dom_file_names(self) -> list[str]:
        return [row.get_by_role("link").inner_text().strip() for row in self._dom_file_rows()]

    def _dom_find_file_id(self, filename: str) -> str | None:
        for row in self._dom_file_rows():
            if row.get_by_role("link").inner_text().strip() == filename:
                return row.get_attribute("data-file-id") or None
        return None

    def _dom_file_id_by_name(self, filename: str) -> str:
        row = self.find_row(self.page, "#file-list > li[data-file-id]", "a", filename)
        return row.get_attribute("data-file-id") or ""

    # ── basic file ops ────────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        slug = self.active_org_handle
        self._goto_files()
        with self.page.expect_file_chooser(timeout=5000) as fc_info:
            self.page.click("input[type=file][name=file]")
        fc_info.value.set_files(
            {"name": filename, "mimeType": "application/octet-stream", "buffer": content}
        )
        upload = self.page.get_by_role("button", name="Upload")
        self.click_and_capture(self.page, upload, "POST", f"/{slug}/files")

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def upload_oversized_file(self, size_mb: int) -> None:
        slug = self.active_org_handle
        # Playwright caps in-memory buffers at 50 MB; write to a tempfile instead.
        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
            tmp.write(b"\x00" * (size_mb * 1024 * 1024))
            tmp_path = tmp.name
        self._goto_files()
        self.page.set_input_files("input[type=file][name=file]", tmp_path)
        upload = self.page.get_by_role("button", name="Upload")
        self.last_response = self.click_and_capture(self.page, upload, "POST", f"/{slug}/files")

    def view_file_list(self) -> None:
        self._goto_files()

    def download_file(self, filename: str) -> None:
        self._goto_files()
        file_id = self._dom_file_id_by_name(filename)
        url = f"{self._files_url()}/{file_id}/download"
        # The endpoint returns 302 → Supabase signed URL → browser starts a file download.
        # Capture the 302 via expect_response; suppress the navigation error that follows.
        with (
            self.page.expect_response(
                lambda r: f"/files/{file_id}/download" in r.url and r.request.method == "GET",
                timeout=10000,
            ) as resp_info,
            contextlib.suppress(Exception),
        ):
            self.page.goto(url, wait_until="networkidle")
        self.last_response = resp_info.value

    def delete_file(self, filename: str) -> None:
        self._goto_files()
        file_id = self._dom_find_file_id(filename)
        assert file_id is not None, f"File '{filename}' not found in DOM"
        delete_btn = self.page.get_by_role("button", name=f"Delete {filename}")
        self.last_response = self.click_and_capture(
            self.page,
            delete_btn,
            "DELETE",
            f"/files/{file_id}",
        )

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        self._goto_files()
        file_id = self._dom_find_file_id(old_filename)
        assert file_id is not None, f"File '{old_filename}' not found in DOM"
        row = self.page.locator(f"[data-file-id='{file_id}']")
        self.page.get_by_role("button", name=f"Rename {old_filename}").click()  # reveal the form
        self.last_response = self.submit_labelled_form(
            self.page,
            {"Filename": new_filename},
            row.get_by_role("button", name="Save"),
            method="PATCH",
            path_token=f"/files/{file_id}",
            root=row,
        )

    # ── sign-in with org naming ───────────────────────────────────────────────

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        delete_user_if_exists(email)
        self.context_for(email)  # isolated context: registers + logs in via _setup_context
        self.set_acting_email(email)  # self.page → email's isolated context
        self.page.goto(f"{self.base_url}/profile", wait_until="load")
        # self.page is on /profile; extract handle from org card link
        link = self.page.locator("[data-organisation-card] a[href*='/dashboard']").first
        href = link.get_attribute("href") or ""
        handle = href.strip("/").split("/")[0]
        assert handle, f"Could not extract org handle for {email}"
        self.active_org_handle = handle
        self.primary_email = email
        self.last_registered_email = email
        # Rename via settings page
        self.page.goto(f"{self.base_url}/{handle}/settings", wait_until="load")
        self.page.fill("input[name=name]", org_name)
        with self.page.expect_response(
            lambda r: f"/{handle}" in r.url and r.request.method == "PATCH"
        ):
            self.page.click("form:has(input[name=name]) button[type=submit]")

    # ── multi-user operations ─────────────────────────────────────────────────

    def add_member_to_org(self, email: str) -> None:
        self.context_for(email)  # ensures member user exists
        self.invite_member(email, "member")  # ty: ignore[unresolved-attribute]
        self.accept_invitation(email)  # ty: ignore[unresolved-attribute]
        self.secondary_handles[email] = self.active_org_handle

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        ctx = self.context_for(email)
        slug = self.secondary_handles.get(email, self.active_org_handle)
        content = b"x" * (size_kb * 1024) if size_kb else b"dummy content"
        page = ctx.new_page()
        try:
            page.goto(f"{self.base_url}/{slug}/files", wait_until="load")
            page.set_input_files(
                "input[type=file][name=file]",
                {"name": filename, "mimeType": "application/octet-stream", "buffer": content},
            )
            with page.expect_response(
                lambda r: f"/{slug}/files" in r.url and r.request.method == "POST",
                timeout=30000,
            ):
                page.get_by_role("button", name="Upload").click()
        finally:
            page.close()

    def create_user_in_org(self, email: str, org_name: str) -> None:
        ctx = self.context_for(email)
        page = ctx.new_page()
        try:
            orgs = self._read_org_cards_from_profile(page)  # ty: ignore[unresolved-attribute]
            assert orgs, f"No org for {email}"
            handle = orgs[0]["handle"]
        finally:
            page.close()
        self.secondary_handles[email] = handle
        # Rename via settings page
        settings_page = ctx.new_page()
        try:
            settings_page.goto(f"{self.base_url}/{handle}/settings", wait_until="load")
            settings_page.fill("input[name=name]", org_name)
            with settings_page.expect_response(
                lambda r: f"/{handle}" in r.url and r.request.method == "PATCH"
            ):
                settings_page.click("form:has(input[name=name]) button[type=submit]")
        finally:
            settings_page.close()

    def promote_to_owner(self) -> None:
        self.set_member_role(self.primary_email, "owner")  # ty: ignore[unresolved-attribute]

    def demote_to_member(self) -> None:
        self.set_member_role(self.primary_email, "member")  # ty: ignore[unresolved-attribute]

    def generate_share_link(self, filename: str) -> None:
        self._goto_files()
        file_id = self._dom_file_id_by_name(filename)
        share_btn = self.page.get_by_role("button", name=f"Share {filename}")
        self.click_and_capture(
            self.page,
            share_btn,
            "POST",
            f"/files/{file_id}/share",
        )
        url_input = self.page.locator(f"#share-result-{file_id} [data-share-url]")
        url_input.wait_for(state="visible")
        self._share_link_url = url_input.input_value()

    def view_file_list_as(self, email: str) -> None:
        ctx = self.context_for(email)
        slug = self.secondary_handles.get(email, self.active_org_handle)
        page = ctx.new_page()
        try:
            self.last_response = page.goto(f"{self.base_url}/{slug}/files", wait_until="load")
            rows = page.locator("#file-list > li[data-file-id]").all()
            self._last_file_names = [row.get_by_role("link").inner_text().strip() for row in rows]
        finally:
            page.close()

    def _goto_and_capture_download(self, page, url: str) -> None:
        """Navigate to a URL that redirects to a storage download; capture the redirect response."""
        with (
            page.expect_response(
                lambda r: r.request.method == "GET" and r.status in (200, 302),
                timeout=10000,
            ) as resp_info,
            contextlib.suppress(Exception),
        ):
            page.goto(url, wait_until="networkidle")
        self.last_response = resp_info.value

    def access_share_link_as(self, email: str) -> None:
        ctx = self.context_for(email)
        share_url = self._share_link_url
        assert share_url, "No share link stored"
        url = share_url if share_url.startswith("http") else f"{self.base_url}{share_url}"
        page = ctx.new_page()
        try:
            self._goto_and_capture_download(page, url)
        finally:
            page.close()

    def access_share_link_unauthenticated(self) -> None:
        assert self.context
        share_url = self._share_link_url
        assert share_url, "No share link stored"
        url = share_url if share_url.startswith("http") else f"{self.base_url}{share_url}"
        anon_ctx = self._browser.new_context()
        page = anon_ctx.new_page()
        try:
            self._goto_and_capture_download(page, url)
        finally:
            page.close()

    # ── assertions ────────────────────────────────────────────────────────────

    def _current_file_names(self) -> list[str]:
        # Names captured from another user's rendered page (view_file_list_as), read from the
        # DOM — never via the JSON API.
        last_names = getattr(self, "_last_file_names", None)
        if last_names is not None:
            self._last_file_names = None
            return last_names
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
        assert self.last_response is not None
        assert self.last_response.status in (200, 302), (
            f"Expected 200 or 302, got {self.last_response.status}"
        )

    def assert_action_denied(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status == 403, f"Expected 403, got {self.last_response.status}"

    def assert_action_rejected(self) -> None:
        assert self.last_response is not None
        assert self.last_response.status in (413, 422), (
            f"Expected 413 or 422, got {self.last_response.status}"
        )

    def upload_file_with_raw_filename(self, filename: str) -> None:
        slug = self.active_org_handle
        self._goto_files()
        self.page.set_input_files(
            "input[type=file][name=file]",
            {"name": filename, "mimeType": "application/octet-stream", "buffer": b"content"},
        )
        upload = self.page.get_by_role("button", name="Upload")
        self.last_response = self.click_and_capture(self.page, upload, "POST", f"/{slug}/files")

    def assert_upload_rejected(self, status: int) -> None:
        assert self.last_response is not None
        assert self.last_response.status == status, (
            f"Expected {status}, got {self.last_response.status}: {self.last_response.text()}"
        )

    def assert_file_metadata(self, filename: str, size: str, email: str, date: str) -> None:
        self._goto_files()
        for row in self._dom_file_rows():
            if row.get_by_role("link").inner_text().strip() == filename:
                meta = row.locator(".file-meta").inner_text()  # KEEP: text read, no ARIA action
                assert email in meta, f"Expected {email!r} in metadata, got: {meta!r}"
                if size.endswith(" KB"):
                    assert size in meta, f"Expected {size!r} in metadata, got: {meta!r}"
                # Date check skipped: set_current_date can't override live server clock
                return
        raise AssertionError(f"File '{filename}' not found in DOM")
