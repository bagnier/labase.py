import httpx

from apps.auth.tests.given_helpers import create_user, delete_user_if_exists, user_id_for_email
from apps.organizations.tests.given_helpers import (
    add_membership,
    create_org_for_user,
    delete_org,
    set_membership_role,
)
from apps.shared.settings import get_settings
from tests.e2e.drivers.api_base import VISITOR, ApiBase

_PASSWORD = "Secret1!"


class OrgFileApiMixin(ApiBase):
    primary_email: str
    secondary_handles: dict[str, str]
    share_link_url: str | None
    active_org_handle: str
    last_registered_email: str | None

    def __init__(self) -> None:
        super().__init__()
        self._test_org_ids: list[str] = []

    # ── lifecycle hooks (extend the substrate via super()) ─────────────────────
    def reset_session(self) -> None:
        self.response: httpx.Response | None = None
        self.secondary_handles = {}
        self.share_link_url = None
        self.primary_email = ""
        self.active_org_handle = ""
        self.last_registered_email = None
        get_settings("files")._raw = None  # restore declared defaults between scenarios
        super().reset_session()

    def _cleanup_committed_data(self) -> None:
        self._cleanup_orgs()

    # ── external (non-transactional) orgs ──────────────────────────────────────
    # File tests must create the primary org outside the test transaction so that
    # Supabase Storage RLS policies can see it; those orgs are deleted here rather
    # than via transaction rollback.
    def track_org_id(self, org_id: str) -> None:
        if org_id not in self._test_org_ids:
            self._test_org_ids.append(org_id)

    def _cleanup_orgs(self) -> None:
        for org_id in self._test_org_ids:
            delete_org(org_id)
        self._test_org_ids.clear()

    def _org_url(self, path: str, slug: str | None = None) -> str:
        s = slug or getattr(self, "active_org_handle", "")
        return f"/{s}{path}"

    def _list_files_with(self, client: httpx.Client, slug: str) -> list[dict]:
        resp = client.get(f"/{slug}/files")
        assert resp.status_code == 200, f"list_files got {resp.status_code}: {resp.text}"
        return resp.json()

    def _list_files(self) -> list[dict]:
        return self._list_files_with(self.client(), getattr(self, "active_org_handle", ""))

    def _file_id_by_name(self, filename: str) -> str:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        raise AssertionError(f"File '{filename}' not found in list")

    def _get_primary_org_id(self) -> str:
        resp = self.client().get("/organizations")
        assert resp.status_code == 200 and resp.json(), "Cannot find primary org"
        return resp.json()[0]["id"]

    # ── sign-in with org naming ───────────────────────────────────────────────

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        # Supabase Storage RLS queries the *committed* database, so the org must
        # exist outside any test transaction — hence the admin helper, not HTTP.
        self.primary_email = email
        self.last_registered_email = email
        delete_user_if_exists(email)
        user_id = create_user(email, _PASSWORD)
        self._track_auth_email(email)
        org = create_org_for_user(org_name, user_id)
        self.track_org_id(org["id"])
        self.active_org_handle = org["handle"]
        # Log in on a client dedicated to this email — never the current acting client, which
        # may belong to another already-signed-in user (e.g. an admin) and would be clobbered.
        client = self._clients.get(email) or self._make_client()
        client.post("/auth/login", json={"email": email, "password": _PASSWORD})
        self._clients[email] = client
        self.set_acting_email(email)

    # ── file operations ───────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        self.response = self.client().post(
            self._org_url("/files"),
            files={"file": (filename, content, "application/octet-stream")},
        )

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def upload_file_with_raw_filename(self, filename: str) -> None:
        self.response = self.client().post(
            self._org_url("/files"),
            files={"file": (filename, b"content", "application/octet-stream")},
        )

    def assert_upload_rejected(self, status: int) -> None:
        assert self.response is not None
        assert self.response.status_code == status, (
            f"Expected {status}, got {self.response.status_code}: {self.response.text}"
        )

    def upload_oversized_file(self, size_mb: int) -> None:
        content = b"\x00" * (size_mb * 1024 * 1024)
        self.response = self.client().post(
            self._org_url("/files"),
            files={"file": ("big.bin", content, "application/octet-stream")},
        )

    def view_file_list(self) -> None:
        self.response = self.client().get(self._org_url("/files"))
        self._last_file_list: list[dict] | None = None

    def download_file(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        self.response = self.client().get(self._org_url(f"/files/{file_id}/download"))

    def _find_file_id(self, filename: str) -> str | None:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        return None

    def delete_file(self, filename: str) -> None:
        file_id = self._find_file_id(filename)
        assert file_id is not None, f"File '{filename}' not found"
        self.response = self.client().delete(self._org_url(f"/files/{file_id}"))

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        file_id = self._find_file_id(old_filename)
        assert file_id is not None, f"File '{old_filename}' not found"
        self.response = self.client().patch(
            self._org_url(f"/files/{file_id}"), json={"filename": new_filename}
        )

    # ── multi-user operations ─────────────────────────────────────────────────

    def add_member_to_org(self, email: str) -> None:
        # Membership must be committed to the real DB so Supabase Storage RLS can verify
        # it when the member uploads files. Same constraint as sign_in_within_org.
        self.client_for(email)  # ensure user is created and logged in
        org_id = self._get_primary_org_id()
        user_id = user_id_for_email(email)
        add_membership(org_id, user_id, role="member")
        self.secondary_handles[email] = self.active_org_handle

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        client = self.client_for(email)
        slug = self.secondary_handles.get(email, self.active_org_handle)
        content = b"x" * (size_kb * 1024) if size_kb else b"dummy content"
        client.post(
            f"/{slug}/files",
            files={"file": (filename, content, "application/octet-stream")},
        )

    def create_user_in_org(self, email: str, org_name: str) -> None:
        client = self.client_for(email)
        resp = client.get("/organizations")
        if resp.status_code == 200 and resp.json():
            slug = resp.json()[0]["handle"]
            self.secondary_handles[email] = slug
            client.patch(f"/{slug}", json={"name": org_name})

    def promote_to_owner(self) -> None:
        # Uses admin helper to bypass last-owner constraint during test setup.
        org_id = self._get_primary_org_id()
        user_id = user_id_for_email(self.primary_email)
        set_membership_role(org_id, user_id, "owner")

    def demote_to_member(self) -> None:
        # Uses admin helper to bypass last-owner constraint during test setup.
        org_id = self._get_primary_org_id()
        user_id = user_id_for_email(self.primary_email)
        set_membership_role(org_id, user_id, "member")

    def generate_share_link(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        resp = self.client().post(self._org_url(f"/files/{file_id}/share"))
        assert resp.status_code == 200, f"share link generation failed: {resp.text}"
        self.share_link_url = resp.json()["url"]

    def view_file_list_as(self, email: str) -> None:
        client = self.client_for(email)
        slug = self.secondary_handles.get(email, self.active_org_handle)
        self.response = client.get(f"/{slug}/files")
        assert self.response.status_code == 200, (
            f"view_file_list_as got {self.response.status_code}"
        )
        self._last_file_list = self.response.json()

    def access_share_link_as(self, email: str) -> None:
        assert self.share_link_url, "No share link stored"
        self.response = self.client_for(email).get(self.share_link_url)

    def access_share_link_unauthenticated(self) -> None:
        assert self.share_link_url, "No share link stored"
        self.response = self.client_for(VISITOR).get(self.share_link_url)

    # ── assertions ────────────────────────────────────────────────────────────

    def _current_file_list(self) -> list[dict]:
        lfl = getattr(self, "_last_file_list", None)
        if lfl is not None:
            self._last_file_list = None
            return lfl
        return self._list_files()

    def assert_file_visible(self, filename: str) -> None:
        names = [f["filename"] for f in self._current_file_list()]
        assert filename in names, f"'{filename}' not found in file list: {names}"

    def assert_file_absent(self, filename: str) -> None:
        names = [f["filename"] for f in self._current_file_list()]
        assert filename not in names, f"'{filename}' should be absent but found in: {names}"

    def assert_download_succeeds(self) -> None:
        assert self.response is not None
        assert self.response.status_code in (200, 302), (
            f"Expected 200 or 302, got {self.response.status_code}"
        )

    def assert_action_rejected(self) -> None:
        assert self.response is not None
        assert self.response.status_code in (413, 422), (
            f"Expected 413 or 422, got {self.response.status_code}"
        )

    def assert_file_metadata(self, filename: str, size: str, email: str, date: str) -> None:
        files = self._list_files()
        match = next((f for f in files if f["filename"] == filename), None)
        assert match is not None, f"'{filename}' not found in file list"
        assert match["uploader_email"] == email, (
            f"Expected uploader_email={email!r}, got {match['uploader_email']!r}"
        )
        if size.endswith(" KB"):
            expected_kb = int(size[:-3])
            actual_kb = round(match["size_bytes"] / 1024)
            assert actual_kb == expected_kb, (
                f"Expected ~{expected_kb} KB, got {actual_kb} KB (size_bytes={match['size_bytes']})"
            )
        assert match["created_at"].startswith(date), (
            f"Expected created_at to start with {date!r}, got {match['created_at']!r}"
        )
