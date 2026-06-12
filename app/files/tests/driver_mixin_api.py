import uuid

import httpx

from app.auth.tests.admin_helpers import create_user as _admin_create_user
from app.main import app
from app.organizations.infra.repository import OrganizationRepository
from app.shared.config import get_settings
from app.shared.persistence.database import _admin_session_factory
from tests.e2e.drivers.protocols import ApiProtocol

_PASSWORD = "Secret1!"


class OrgFileApiMixin(ApiProtocol):
    _primary_email: str
    _secondary_clients: dict[str, httpx.AsyncClient]
    _secondary_slugs: dict[str, str]
    _share_link_url: str | None
    _active_org_slug: str

    def _ensure_multi_user(self) -> None:
        if not hasattr(self, "_secondary_clients"):
            self._secondary_clients = {}
        if not hasattr(self, "_secondary_slugs"):
            self._secondary_slugs = {}
        if not hasattr(self, "_share_link_url"):
            self._share_link_url = None
        if not hasattr(self, "_primary_email"):
            self._primary_email = ""
        if not hasattr(self, "_active_org_slug"):
            self._active_org_slug = ""

    def _reset_multi_user_state(self) -> None:
        if not hasattr(self, "_known_test_emails"):
            self._known_test_emails: set[str] = set()
        if hasattr(self, "_primary_email") and self._primary_email:
            self._known_test_emails.add(self._primary_email)
        if hasattr(self, "_secondary_clients"):
            self._known_test_emails.update(self._secondary_clients.keys())
        self._secondary_clients = {}
        self._secondary_slugs = {}
        self._share_link_url = None
        self._primary_email = ""
        self._active_org_slug = ""
        self._org_list_response = None  # reset cached org list from OrgApiMixin
        self._primary_client_backup = None  # type: ignore[assignment]
        self._restore_clock()

    def _admin_headers(self) -> dict:
        s = get_settings()
        return {
            "apikey": s.supabase_service_role_key,
            "Authorization": f"Bearer {s.supabase_service_role_key}",
        }

    def _org_url(self, path: str, slug: str | None = None) -> str:
        s = slug or getattr(self, "_active_org_slug", "")
        return f"/orgs/{s}{path}"

    def _org_url_for(self, email: str, path: str) -> str:
        slug = self._secondary_slugs.get(email, getattr(self, "_active_org_slug", ""))
        return f"/orgs/{slug}{path}"

    def _fetch_slug_for(self, client: httpx.AsyncClient) -> str:
        resp = self._run(client.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200 and resp.json(), "Cannot fetch org slug"
        return resp.json()[0]["slug"]

    def _list_files_with(self, client: httpx.AsyncClient, slug: str) -> list[dict]:
        resp = self._run(client.get(f"/orgs/{slug}/files", headers={"accept": "application/json"}))
        assert resp.status_code == 200, f"list_files got {resp.status_code}: {resp.text}"
        return resp.json()

    def _list_files(self) -> list[dict]:
        return self._list_files_with(self._c, getattr(self, "_active_org_slug", ""))

    def _file_id_by_name(self, filename: str) -> str:
        for f in self._list_files():
            if f["filename"] == filename:
                return f["id"]
        raise AssertionError(f"File '{filename}' not found in list")

    def _get_primary_org_id(self) -> str:
        resp = self._run(self._c.get("/organizations", headers={"accept": "application/json"}))
        assert resp.status_code == 200 and resp.json(), "Cannot find primary org"
        return resp.json()[0]["id"]

    def _make_client_for(self, email: str) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        client = httpx.AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        )
        self._run(client.post("/auth/register", data={"email": email, "password": _PASSWORD}))
        self._run(client.post("/auth/login", data={"email": email, "password": _PASSWORD}))
        return client

    def _client_for(self, email: str) -> httpx.AsyncClient:
        self._ensure_multi_user()
        if email not in self._secondary_clients:
            self._secondary_clients[email] = self._make_client_for(email)
        return self._secondary_clients[email]

    def _user_id_for_email(self, email: str) -> str:
        s = get_settings()
        resp = httpx.get(
            f"{s.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        all_users = resp.json().get("users", [])
        matched = [u for u in all_users if u.get("email") == email]
        assert matched, (
            f"User {email!r} not found in Supabase (got {[u.get('email') for u in all_users]})"
        )
        return matched[0]["id"]

    # ── sign-in with org naming ───────────────────────────────────────────────

    def _delete_supabase_user(self, email: str) -> None:
        s = get_settings()
        resp = httpx.get(
            f"{s.supabase_url}/auth/v1/admin/users",
            params={"email": email},
            headers=self._admin_headers(),
        )
        for user in resp.json().get("users", []):
            httpx.delete(
                f"{s.supabase_url}/auth/v1/admin/users/{user['id']}",
                headers=self._admin_headers(),
            )

    def _cleanup_example_users(self) -> None:
        s = get_settings()
        page = 1
        while True:
            resp = httpx.get(
                f"{s.supabase_url}/auth/v1/admin/users?per_page=1000&page={page}",
                headers=self._admin_headers(),
            )
            users = resp.json().get("users", [])
            for user in users:
                ue = user.get("email", "")
                if ue.endswith("@example.com"):
                    httpx.delete(
                        f"{s.supabase_url}/auth/v1/admin/users/{user['id']}",
                        headers=self._admin_headers(),
                    )
            if len(users) < 1000:
                break
            page += 1

    def sign_in_within_org(self, email: str, org_name: str) -> None:
        self._ensure_multi_user()
        self._primary_email = email
        self._last_registered_email = email
        self._cleanup_example_users()
        self._known_test_emails = set()
        # Use admin API to create user: avoids GoTrue timing race where the new
        # auth.users row isn't visible via direct Postgres FK check when using sign_up.
        user_id_str = _admin_create_user(email, _PASSWORD)

        async def _create_org() -> str:
            async with _admin_session_factory()() as session:
                repo = OrganizationRepository(session)
                org = await repo.create_with_owner(
                    name=org_name, auth_user_id=uuid.UUID(user_id_str)
                )
                return org.slug

        self._active_org_slug = self._run(_create_org())
        self._run(self._c.post("/auth/login", data={"email": email, "password": _PASSWORD}))

    # ── file operations ───────────────────────────────────────────────────────

    def upload_file(self, filename: str, content: bytes = b"dummy content") -> None:
        self._response = self._run(
            self._c.post(
                self._org_url("/files"),
                files={"file": (filename, content, "application/octet-stream")},
            )
        )

    def have_uploaded_file(self, filename: str) -> None:
        self.upload_file(filename)

    def upload_oversized_file(self, size_mb: int) -> None:
        content = b"\x00" * (size_mb * 1024 * 1024)
        self._response = self._run(
            self._c.post(
                self._org_url("/files"),
                files={"file": ("big.bin", content, "application/octet-stream")},
            )
        )

    def view_file_list(self) -> None:
        self._response = self._run(self._c.get(self._org_url("/files")))
        self._last_file_list: list[dict] | None = None

    def download_file(self, filename: str) -> None:
        file_id = self._file_id_by_name(filename)
        self._response = self._run(self._c.get(self._org_url(f"/files/{file_id}/download")))

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
        self._response = self._run(
            self._c.delete(
                self._org_url(f"/files/{file_id}"), headers={"accept": "application/json"}
            )
        )

    def rename_file(self, old_filename: str, new_filename: str) -> None:
        file_id = self._find_file_id(old_filename)
        if file_id is None:
            self.rename_todo(old_filename, new_filename)
            return
        self._response = self._run(
            self._c.patch(
                self._org_url(f"/files/{file_id}"),
                json={"filename": new_filename},
                headers={"accept": "application/json"},
            )
        )

    # ── multi-user operations ─────────────────────────────────────────────────

    def add_member_to_org(self, email: str) -> None:
        self._ensure_multi_user()
        self._client_for(email)
        user_id = self._user_id_for_email(email)
        org_id = self._get_primary_org_id()

        s = get_settings()
        pg_resp = httpx.post(
            f"{s.supabase_url}/rest/v1/memberships",
            json={"org_id": org_id, "auth_user_id": user_id, "role": "member"},
            headers={
                **self._admin_headers(),
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        assert pg_resp.status_code in (200, 201), f"membership insert failed: {pg_resp.text}"

        # Secondary client points at primary org slug
        self._secondary_slugs[email] = self._active_org_slug

    def upload_file_as(self, email: str, filename: str, size_kb: int | None = None) -> None:
        client = self._client_for(email)
        slug = self._secondary_slugs.get(email, self._active_org_slug)
        content = b"x" * (size_kb * 1024) if size_kb else b"dummy content"
        self._run(
            client.post(
                f"/orgs/{slug}/files",
                files={"file": (filename, content, "application/octet-stream")},
            )
        )

    def create_user_in_org(self, email: str, org_name: str) -> None:
        self._ensure_multi_user()
        client = self._client_for(email)
        resp = self._run(client.get("/organizations", headers={"accept": "application/json"}))
        if resp.status_code == 200 and resp.json():
            org_id = resp.json()[0]["id"]
            slug = resp.json()[0]["slug"]
            self._secondary_slugs[email] = slug
            self._run(
                client.patch(
                    f"/organizations/{org_id}",
                    json={"name": org_name},
                    headers={"accept": "application/json"},
                )
            )

    def promote_to_owner(self) -> None:
        self._ensure_multi_user()
        s = get_settings()
        org_id = self._get_primary_org_id()
        user_id = self._user_id_for_email(self._primary_email)
        pg_resp = httpx.patch(
            f"{s.supabase_url}/rest/v1/memberships",
            params={"org_id": f"eq.{org_id}", "auth_user_id": f"eq.{user_id}"},
            json={"role": "owner"},
            headers={
                **self._admin_headers(),
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        assert pg_resp.status_code in (200, 204), f"promote failed: {pg_resp.text}"

    def demote_to_member(self) -> None:
        self._ensure_multi_user()
        s = get_settings()
        org_id = self._get_primary_org_id()
        user_id = self._user_id_for_email(self._primary_email)
        pg_resp = httpx.patch(
            f"{s.supabase_url}/rest/v1/memberships",
            params={"org_id": f"eq.{org_id}", "auth_user_id": f"eq.{user_id}"},
            json={"role": "member"},
            headers={
                **self._admin_headers(),
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
        )
        assert pg_resp.status_code in (200, 204), f"demote failed: {pg_resp.text}"

    def generate_share_link(self, filename: str) -> None:
        self._ensure_multi_user()
        file_id = self._file_id_by_name(filename)
        resp = self._run(
            self._c.post(
                self._org_url(f"/files/{file_id}/share"), headers={"accept": "application/json"}
            )
        )
        assert resp.status_code == 200, f"share link generation failed: {resp.text}"
        self._share_link_url = resp.json()["url"]

    def view_file_list_as(self, email: str) -> None:
        client = self._client_for(email)
        slug = self._secondary_slugs.get(email, self._active_org_slug)
        self._response = self._run(
            client.get(f"/orgs/{slug}/files", headers={"accept": "application/json"})
        )
        assert self._response.status_code == 200, (
            f"view_file_list_as got {self._response.status_code}"
        )
        self._last_file_list = self._response.json()

    def access_share_link_as(self, email: str) -> None:
        self._ensure_multi_user()
        assert self._share_link_url, "No share link stored"
        client = self._client_for(email)
        self._response = self._run(client.get(self._share_link_url))

    def access_share_link_unauthenticated(self) -> None:
        self._ensure_multi_user()
        assert self._share_link_url, "No share link stored"
        transport = httpx.ASGITransport(app=app)
        anon = httpx.AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        )
        self._response = self._run(anon.get(self._share_link_url))

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
