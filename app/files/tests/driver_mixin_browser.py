from tests.e2e.drivers.protocols import BrowserProtocol


class OrgFileBrowserMixin(BrowserProtocol):
    def _goto_files(self) -> None:
        self._p.goto(f"{self._base_url}/files", wait_until="networkidle")

    def _dom_file_rows(self) -> list:
        return self._p.locator("#file-list > div[data-file-id]").all()

    def _dom_file_names(self) -> list[str]:
        return [row.locator("a").inner_text().strip() for row in self._dom_file_rows()]

    def _dom_file_id_by_name(self, filename: str) -> str:
        for row in self._dom_file_rows():
            if row.locator("a").inner_text().strip() == filename:
                return row.get_attribute("data-file-id") or ""
        raise AssertionError(f"File '{filename}' not found in DOM")

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
        file_id = self._dom_file_id_by_name(filename)
        with self._p.expect_response(
            lambda r: f"/files/{file_id}" in r.url and r.request.method == "DELETE",
            timeout=10000,
        ):
            self._p.click(f"button[data-delete-id='{file_id}']")
        self._goto_files()

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
