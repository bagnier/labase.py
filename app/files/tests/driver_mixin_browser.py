from tests.e2e.drivers.protocols import BrowserProtocol

_PASSWORD = "Secret1!"


class OrgFileBrowserMixin(BrowserProtocol):
    _share_link_url: str | None

    def _goto_files(self) -> None:
        self._p.goto(f"{self._base_url}/files", wait_until="networkidle")

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

    # ── basic file ops ────────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        assert self._context
        self._context.request.post(
            f"{self._base_url}/files",
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
            f"{self._base_url}/files",
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
            f"{self._base_url}/files/{file_id}/download",
        )

    def delete_file(self, filename: str) -> None:
        self._goto_files()
        file_id = self._dom_find_file_id(filename)
        if file_id is None:
            self.delete_todo(filename)
            return
        with self._p.expect_response(
            lambda r: f"/files/{file_id}" in r.url and r.request.method == "DELETE",
            timeout=10000,
        ):
            self._p.click(f"button[data-delete-id='{file_id}']")
        self._goto_files()

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        self._goto_files()
        file_id = self._dom_find_file_id(old_filename)
        if file_id is None:
            self.rename_todo(old_filename, new_filename)
            return
        # Click rename button, fill modal, submit
        self._p.click(f"button[data-rename-id='{file_id}']")
        self._p.fill("#rename-input", new_filename)
        self._p.click("#rename-submit")
        self._goto_files()

    # ── multi-user stubs (API-only; browser scenarios TBD) ────────────────────

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        raise NotImplementedError("sign_in_within_org browser")

    def add_member_to_org(self, email: str) -> None:
        raise NotImplementedError("add_member_to_org browser")

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        raise NotImplementedError("upload_file_as browser")

    def create_user_in_org(self, email: str, org_name: str) -> None:
        raise NotImplementedError("create_user_in_org browser")

    def promote_to_admin(self) -> None:
        raise NotImplementedError("promote_to_admin browser")

    def generate_share_link(self, filename: str) -> None:
        raise NotImplementedError("generate_share_link browser")

    def view_file_list_as(self, email: str) -> None:
        raise NotImplementedError("view_file_list_as browser")

    def access_share_link_as(self, email: str) -> None:
        raise NotImplementedError("access_share_link_as browser")

    def access_share_link_unauthenticated(self) -> None:
        raise NotImplementedError("access_share_link_unauthenticated browser")

    # ── assertions ────────────────────────────────────────────────────────────

    def assert_file_visible(self, filename: str) -> None:
        self._goto_files()
        names = self._dom_file_names()
        assert filename in names, f"'{filename}' not found in #file-list DOM: {names}"

    def assert_file_absent(self, filename: str) -> None:
        self._goto_files()
        names = self._dom_file_names()
        assert filename not in names, (
            f"'{filename}' should be absent but found in #file-list DOM: {names}"
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

    def assert_file_metadata(self, filename: str, size: str, email: str, date: str) -> None:
        self._goto_files()
        for row in self._dom_file_rows():
            if row.locator("a").inner_text().strip() == filename:
                meta = row.locator(".file-meta").inner_text()
                assert email in meta, f"Expected {email!r} in metadata, got: {meta!r}"
                if size.endswith(" KB"):
                    assert size in meta, f"Expected {size!r} in metadata, got: {meta!r}"
                assert date in meta, f"Expected {date!r} in metadata, got: {meta!r}"
                return
        raise AssertionError(f"File '{filename}' not found in DOM")
