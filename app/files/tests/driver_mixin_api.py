import uuid

import httpx
from sqlalchemy import delete

from app.auth.tests.admin_helpers import (
    create_user as _admin_create_user,
)
from app.auth.tests.admin_helpers import (
    delete_user_if_exists,
)
from app.organizations.domain.models import Organization
from app.organizations.infra.repository import OrganizationRepository
from app.organizations.tests.admin_helpers import (
    add_membership as _admin_add_membership,
)
from app.organizations.tests.admin_helpers import (
    set_membership_role as _admin_set_role,
)
from app.shared.persistence.database import admin_session_factory
from tests.e2e.drivers.api_base import ApiBase

_PASSWORD = "Secret1!"


class OrgFileApiMixin(ApiBase):
    _primary_email: str
    _secondary_clients: dict[str, httpx.AsyncClient]
    _secondary_handles: dict[str, str]
    _share_link_url: str | None
    _active_org_handle: str

    def _ensure_multi_user(self) -> None:
        if not hasattr(self, "_secondary_clients"):
            self._secondary_clients = {}
        if not hasattr(self, "_secondary_handles"):
            self._secondary_handles = {}
        if not hasattr(self, "_share_link_url"):
            self._share_link_url = None
        if not hasattr(self, "_primary_email"):
            self._primary_email = ""
        if not hasattr(self, "_active_org_handle"):
            self._active_org_handle = ""

    def __init__(self) -> None:
        super().__init__()
        self._test_org_ids: list[str] = []

    # ── lifecycle hooks (extend the substrate via super()) ─────────────────────
    def reset_session(self) -> None:
        self._secondary_handles = {}
        self._share_link_url = None
        self._primary_email = ""
        self._active_org_handle = ""
        self._org_list_response = None  # cached org list from OrgApiMixin
        self._primary_client_backup = None  # type: ignore[assignment]
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
        if not self._test_org_ids:
            return

        async def _delete() -> None:
            async with admin_session_factory()() as session:
                ids = [uuid.UUID(oid) for oid in self._test_org_ids]
                await session.execute(delete(Organization).where(Organization.id.in_(ids)))
                await session.commit()

        self.run(_delete())
        self._test_org_ids.clear()

    def _org_url(self, path: str, slug: str | None = None) -> str:
        s = slug or getattr(self, "_active_org_handle", "")
        return f"/{s}{path}"

    def _org_url_for(self, email: str, path: str) -> str:
        slug = self._secondary_handles.get(email, getattr(self, "_active_org_handle", ""))
        return f"/{slug}{path}"

    def _fetch_slug_for(self, client: httpx.AsyncClient) -> str:
        resp = self.json_client("GET", "/organizations", client)
        assert resp.status_code == 200 and resp.json(), "Cannot fetch org slug"
        return resp.json()[0]["handle"]

    def _list_files_with(self, client: httpx.AsyncClient, slug: str) -> list[dict]:
        resp = self.json_client("GET", f"/{slug}/files", client)
        assert resp.status_code == 200, f"list_files got {resp.status_code}: {resp.text}"
        return resp.json()

    def _list_files(self) -> list[dict]:
        return self._list_files_with(self.client, getattr(self, "_active_org_handle", ""))

    def _file_id_by_name(self, filename: str) -> str:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        raise AssertionError(f"File '{filename}' not found in list")

    def _get_primary_org_id(self) -> str:
        resp = self.json_client("GET", "/organizations")
        assert resp.status_code == 200 and resp.json(), "Cannot find primary org"
        return resp.json()[0]["id"]

    # ── sign-in with org naming ───────────────────────────────────────────────

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        # Supabase Storage RLS policies query the *committed* database, so the org must
        # exist outside the test transaction. We create the user and org via admin APIs
        # (bypassing the transaction rollback) and clean up in _cleanup_orgs().
        self._ensure_multi_user()
        self._primary_email = email
        self._last_registered_email = email
        delete_user_if_exists(email)
        user_id_str = _admin_create_user(email, _PASSWORD)
        self.track_auth_email(email)

        async def _create_org() -> tuple[str, str]:
            async with admin_session_factory()() as session:
                repo = OrganizationRepository(session)
                org = await repo.create_with_owner(
                    name=org_name, auth_user_id=uuid.UUID(user_id_str)
                )
                await session.commit()
                return str(org.id), org.handle

        org_id, handle = self.run(_create_org())
        self.track_org_id(org_id)
        self._active_org_handle = handle
        self.run(self.client.post("/auth/login", data={"email": email, "password": _PASSWORD}))

    # ── file operations ───────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        self._response = self.run(
            self.client.post(
                self._org_url("/files"),
                files={"file": (filename, content, "application/octet-stream")},
            )
        )

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def upload_file_with_raw_filename(self, filename: str) -> None:
        self._response = self.run(
            self.client.post(
                self._org_url("/files"),
                files={"file": (filename, b"content", "application/octet-stream")},
            )
        )

    def assert_upload_rejected(self, status: int) -> None:
        assert self._response is not None
        assert self._response.status_code == status, (
            f"Expected {status}, got {self._response.status_code}: {self._response.text}"
        )

    def upload_oversized_file(self, size_mb: int) -> None:
        content = b"\x00" * (size_mb * 1024 * 1024)
        self._response = self.run(
            self.client.post(
                self._org_url("/files"),
                files={"file": ("big.bin", content, "application/octet-stream")},
            )
        )

    def view_file_list(self) -> None:
        self._response = self.run(self.client.get(self._org_url("/files")))
        self._last_file_list: list[dict] | None = None

    def download_file(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        self._response = self.run(self.client.get(self._org_url(f"/files/{file_id}/download")))

    def _find_file_id(self, filename: str) -> str | None:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        return None

    def delete_file(self, filename: str) -> None:
        file_id = self._find_file_id(filename)
        if file_id is None:
            self.delete_todo(filename)
            return
        self._response = self.json_client("DELETE", self._org_url(f"/files/{file_id}"))

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        file_id = self._find_file_id(old_filename)
        if file_id is None:
            self.rename_todo(old_filename, new_filename)
            return
        self._response = self.json_client(
            "PATCH", self._org_url(f"/files/{file_id}"), json={"filename": new_filename}
        )

    # ── multi-user operations ─────────────────────────────────────────────────

    def add_member_to_org(self, email: str) -> None:
        # Membership must be committed to the real DB so Supabase Storage RLS can verify
        # it when the member uploads files. Same constraint as sign_in_within_org.
        self._ensure_multi_user()
        self._client_for(email)  # ensure user is created and logged in
        org_id = self._get_primary_org_id()
        user_id = self._user_id_for_email(email)
        _admin_add_membership(org_id, user_id, role="member")
        self._secondary_handles[email] = self._active_org_handle

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        client = self._client_for(email)
        slug = self._secondary_handles.get(email, self._active_org_handle)
        content = b"x" * (size_kb * 1024) if size_kb else b"dummy content"
        self.run(
            client.post(
                f"/{slug}/files",
                files={"file": (filename, content, "application/octet-stream")},
            )
        )

    def create_user_in_org(self, email: str, org_name: str) -> None:
        self._ensure_multi_user()
        client = self._client_for(email)
        resp = self.json_client("GET", "/organizations", client)
        if resp.status_code == 200 and resp.json():
            slug = resp.json()[0]["handle"]
            self._secondary_handles[email] = slug
            self.json_client("PATCH", f"/{slug}", client, data={"name": org_name})

    def promote_to_owner(self) -> None:
        # Uses admin helper to bypass last-owner constraint during test setup.
        self._ensure_multi_user()
        org_id = self._get_primary_org_id()
        user_id = self._user_id_for_email(self._primary_email)
        _admin_set_role(org_id, user_id, "owner")

    def demote_to_member(self) -> None:
        # Uses admin helper to bypass last-owner constraint during test setup.
        self._ensure_multi_user()
        org_id = self._get_primary_org_id()
        user_id = self._user_id_for_email(self._primary_email)
        _admin_set_role(org_id, user_id, "member")

    def generate_share_link(self, filename: str) -> None:
        self._ensure_multi_user()
        file_id = self._file_id_by_name(filename)
        resp = self.json_client("POST", self._org_url(f"/files/{file_id}/share"))
        assert resp.status_code == 200, f"share link generation failed: {resp.text}"
        self._share_link_url = resp.json()["url"]

    def view_file_list_as(self, email: str) -> None:
        client = self._client_for(email)
        slug = self._secondary_handles.get(email, self._active_org_handle)
        self._response = self.json_client("GET", f"/{slug}/files", client)
        assert self._response.status_code == 200, (
            f"view_file_list_as got {self._response.status_code}"
        )
        self._last_file_list = self._response.json()

    def access_share_link_as(self, email: str) -> None:
        self._ensure_multi_user()
        assert self._share_link_url, "No share link stored"
        client = self._client_for(email)
        self._response = self.run(client.get(self._share_link_url))

    def access_share_link_unauthenticated(self) -> None:
        self._ensure_multi_user()
        assert self._share_link_url, "No share link stored"
        anon = self.make_client()
        self._response = self.run(anon.get(self._share_link_url))

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
        assert self._response is not None
        assert self._response.status_code in (200, 302), (
            f"Expected 200 or 302, got {self._response.status_code}"
        )

    def assert_action_denied(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 403, f"Expected 403, got {self._response.status_code}"

    def assert_action_rejected(self) -> None:
        assert self._response is not None
        assert self._response.status_code in (413, 422), (
            f"Expected 413 or 422, got {self._response.status_code}"
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
