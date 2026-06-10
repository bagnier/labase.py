from tests.e2e.drivers.protocols import ApiProtocol


class OrgFileApiMixin(ApiProtocol):
    def _list_files(self) -> list[dict]:
        resp = self._run(self._c.get("/files", headers={"accept": "application/json"}))
        return resp.json()

    def _file_id_by_name(self, filename: str) -> str:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        raise AssertionError(f"File '{filename}' not found in list")

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        self._response = self._run(
            self._c.post(
                "/files",
                files={"file": (filename, content, "application/octet-stream")},
            )
        )

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def view_file_list(self) -> None:
        self._response = self._run(self._c.get("/files"))

    def download_file(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        self._response = self._run(self._c.get(f"/files/{file_id}/download"))

    def delete_file(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        self._response = self._run(self._c.delete(f"/files/{file_id}"))

    def assert_file_visible(self, filename: str) -> None:
        names = [f["filename"] for f in self._list_files()]
        assert filename in names, f"'{filename}' not found in file list: {names}"

    def assert_file_absent(self, filename: str) -> None:
        names = [f["filename"] for f in self._list_files()]
        assert filename not in names, f"'{filename}' should be absent but found in: {names}"

    def assert_download_succeeds(self) -> None:
        assert self._response is not None
        assert self._response.status_code in (200, 302), (
            f"Expected 200 or 302, got {self._response.status_code}"
        )
