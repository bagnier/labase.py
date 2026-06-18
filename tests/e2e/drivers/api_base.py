"""Technical substrate to execute API tests, in-process over httpx/ASGI.

Owns what every *ApiMixin needs to run but that is not feature behaviour: the
event loop, the http client(s), JSON content negotiation, the rolled-back test
transaction and the authenticated multi-user clients shared across features.
Feature mixins inherit this; the concrete ApiDriver just assembles them.
No typing Protocol: this base *is* the shared contract.
"""

import httpx

from app.auth.infra.session import get_rls_session
from app.auth.tests.admin_helpers import delete_user_if_exists, find_users
from app.main import app
from app.shared.persistence.database import (
    _admin_engine,
    get_admin_session,
    get_user_session,
)
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.background_loop import BackgroundLoop

_PASSWORD = "Secret1!"


class ApiBase:
    def __init__(self) -> None:
        self._bg = BackgroundLoop()
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None
        self._test_auth_emails: list[str] = []
        self._secondary_clients: dict[str, httpx.AsyncClient] = {}

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._bg.start()
        self._client = self.make_client()

    def stop(self) -> None:
        if self._client:
            self._bg.run(self._client.aclose())
        self._bg.stop()

    def run(self, coro):
        return self._bg.run(coro)

    def make_client(self) -> httpx.AsyncClient:
        transport = httpx.ASGITransport(app=app)
        return httpx.AsyncClient(
            transport=transport, base_url="http://testserver", follow_redirects=False
        )

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

    def reset_session(self) -> None:
        self._client = self.make_client()
        self._secondary_clients = {}

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        """Open the rolled-back test transaction and route all sessions onto it."""
        db._test_connection = self.run(db.begin_test_transaction(_admin_engine()))
        app.dependency_overrides[get_user_session] = db.override_get_session
        app.dependency_overrides[get_admin_session] = db.override_get_session
        app.dependency_overrides[get_rls_session] = db.override_get_rls_session

    def teardown_test(self) -> None:
        """Roll back the test transaction, then clean up data committed outside it.

        Order is load-bearing: the test transaction must be rolled back *first* to
        release its row locks, then feature-committed data (e.g. orgs) is deleted,
        then the auth users that own it — deleting an owner before its org would
        violate the membership FK.
        """
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_rls_session, None)
        conn = db._test_connection
        db._test_connection = None
        if conn is not None:
            self.run(db.end_test_transaction(conn))
        self._cleanup_committed_data()
        self._cleanup_auth_users()

    def _cleanup_committed_data(self) -> None:
        """Hook: feature mixins override this to delete data they committed
        outside the rolled-back test transaction."""

    # ── JSON (REST) calls ──────────────────────────────────────────────────────
    # Single chokepoint for content-negotiated JSON requests: forces the
    # ``accept: application/json`` header so the app serves REST instead of HTML.
    # HTML/HTMX flows keep using self.client directly. A future typed OpenAPI
    # client could be wired in here without touching call sites.
    def json_client(self, method: str, path: str, client: httpx.AsyncClient | None = None, **kw):
        headers = {"accept": "application/json", **kw.pop("headers", {})}
        return self.run((client or self.client).request(method, path, headers=headers, **kw))

    # ── external (non-transactional) auth users ────────────────────────────────
    # Supabase auth users live outside the rolled-back test transaction, so they
    # are tracked here and deleted in teardown rather than rolled back. Shared by
    # the auth and files features, hence on the base rather than a single mixin.
    def track_auth_email(self, email: str) -> None:
        if email not in self._test_auth_emails:
            self._test_auth_emails.append(email)

    def _cleanup_auth_users(self) -> None:
        for email in self._test_auth_emails:
            self._delete_user_if_exists(email)
        self._test_auth_emails.clear()

    def _delete_user_if_exists(self, email: str) -> None:
        delete_user_if_exists(email)

    # ── authenticated multi-user clients (shared by org/files/learning) ─────────
    def _make_client_for(self, email: str) -> httpx.AsyncClient:
        client = self.make_client()
        self.run(client.post("/auth/register", data={"email": email, "password": _PASSWORD}))
        self.run(client.post("/auth/login", data={"email": email, "password": _PASSWORD}))
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

    # ── cross-feature methods (real impl provided by feature mixins) ───────────
    def delete_todo(self, title: str) -> None: ...

    def rename_todo(self, title: str, new_title: str) -> None: ...
