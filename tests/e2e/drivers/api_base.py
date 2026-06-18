"""Technical substrate to execute API tests, in-process over httpx/ASGI.

Owns everything the *ApiMixin feature classes need to run but that is not feature
behaviour: the event loop, the http client(s), JSON content negotiation, the
rolled-back test transaction, the deterministic clock and multi-user client
management. Feature mixins inherit this; the concrete ApiDriver just assembles
them. No typing Protocol: this base *is* the shared contract.
"""

import asyncio
import threading
import uuid

import httpx
from sqlalchemy import delete

from app.auth.infra.session import get_rls_session
from app.auth.tests.admin_helpers import delete_user_if_exists, find_users
from app.main import app
from app.organizations.domain.models import Organization
from app.shared.persistence.database import (
    _admin_engine,
    admin_session_factory,
    get_admin_session,
    get_user_session,
)
from tests import db

_PASSWORD = "Secret1!"


class ApiBase:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None
        self._test_auth_emails: list[str] = []
        self._test_org_ids: list[str] = []
        self._secondary_clients: dict[str, httpx.AsyncClient] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._client = self._make_client()

    def stop(self) -> None:
        if self._client and self._loop:
            asyncio.run_coroutine_threadsafe(self._client.aclose(), self._loop).result()
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join()

    def _run(self, coro):
        assert self._loop
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def _make_client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        )

    @property
    def _c(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

    def reset_session(self) -> None:
        self._client = self._make_client()
        self._reset_multi_user_state()

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        """Open the rolled-back test transaction and route all sessions onto it."""
        db._test_connection = self._run(db.begin_test_transaction(_admin_engine()))
        app.dependency_overrides[get_user_session] = db.override_get_session
        app.dependency_overrides[get_admin_session] = db.override_get_session
        app.dependency_overrides[get_rls_session] = db.override_get_rls_session

    def teardown_test(self) -> None:
        """Roll back the test transaction and clean up out-of-transaction data."""
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_rls_session, None)
        conn = db._test_connection
        db._test_connection = None
        if conn is not None:
            self._run(db.end_test_transaction(conn))
        self.cleanup_test_orgs()
        self.cleanup_test_auth_users()

    # ── JSON (REST) calls ──────────────────────────────────────────────────────
    # Single chokepoint for content-negotiated JSON requests: forces the
    # ``accept: application/json`` header so the app serves REST instead of HTML.
    # HTML/HTMX flows keep using self._c directly. A future typed OpenAPI client
    # could be wired in here without touching call sites.
    def _json(self, method: str, path: str, client: httpx.AsyncClient | None = None, **kw):
        headers = {"accept": "application/json", **kw.pop("headers", {})}
        return self._run((client or self._c).request(method, path, headers=headers, **kw))

    # ── tracking / cleanup of out-of-transaction data ──────────────────────────
    def track_auth_email(self, email: str) -> None:
        """Registers an auth user email created during the current test."""
        if email not in self._test_auth_emails:
            self._test_auth_emails.append(email)

    def track_org_id(self, org_id: str) -> None:
        """Registers an org committed to the real DB during the current test.

        File tests must create the primary org outside the test transaction so
        that Supabase Storage RLS policies can see it. Those orgs are cleaned up
        here rather than via transaction rollback.
        """
        if org_id not in self._test_org_ids:
            self._test_org_ids.append(org_id)

    def cleanup_test_orgs(self) -> None:
        """Deletes orgs committed to the real DB (outside the test transaction)."""
        if not self._test_org_ids:
            return

        async def _delete() -> None:
            async with admin_session_factory()() as session:
                ids = [uuid.UUID(oid) for oid in self._test_org_ids]
                await session.execute(delete(Organization).where(Organization.id.in_(ids)))
                await session.commit()

        self._run(_delete())
        self._test_org_ids.clear()

    def cleanup_test_auth_users(self) -> None:
        """Deletes all Supabase auth users created during the current test."""
        for email in self._test_auth_emails:
            self._delete_user_if_exists(email)
        self._test_auth_emails.clear()

    def _delete_user_if_exists(self, email: str) -> None:
        delete_user_if_exists(email)

    # ── multi-user client management ───────────────────────────────────────────
    def _make_client_for(self, email: str) -> httpx.AsyncClient:
        client = self._make_client()
        self._run(client.post("/auth/register", data={"email": email, "password": _PASSWORD}))
        self._run(client.post("/auth/login", data={"email": email, "password": _PASSWORD}))
        self.track_auth_email(email)
        return client

    def _client_for(self, email: str) -> httpx.AsyncClient:
        if email not in self._secondary_clients:
            self._secondary_clients[email] = self._make_client_for(email)
        return self._secondary_clients[email]

    def _user_id_for_email(self, email: str) -> str:
        users = find_users(email)
        assert users, f"User {email!r} not found in Supabase"
        return users[0].id

    def _reset_multi_user_state(self) -> None:
        """Default reset; feature mixins extend it for their own multi-user state."""
        self._secondary_clients = {}

    # ── HTTP assertions ────────────────────────────────────────────────────────
    def visit(self, path: str) -> None:
        self._response = self._run(self._c.get(path))

    def assert_page_accessible(self, path: str, contains: str) -> None:
        resp = self._run(self._c.get(path))
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert contains in resp.text, f"'{contains}' not found in response"

    def assert_text(self, text: str) -> None:
        assert self._response is not None
        assert text in self._response.text, f"'{text}' not found in:\n{self._response.text[:500]}"

    def assert_page_loaded(self) -> None:
        assert self._response is not None
        assert self._response.status_code == 200, f"Expected 200, got {self._response.status_code}"

    # ── cross-feature methods (real impl provided by feature mixins) ───────────
    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...
