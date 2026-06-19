"""Technical substrate for API tests: event loop, unified multi-user client
management, JSON content negotiation, rolled-back test transaction.
Feature mixins inherit this; ApiDriver assembles them."""

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
_VISITOR = "visitor"  # sentinel — unauthenticated client, no associated user


class ApiBase:
    def __init__(self) -> None:
        self._bg = BackgroundLoop()
        self.response: httpx.Response | None = None
        self.last_registered_email: str | None = None
        self._test_auth_emails: list[str] = []
        self._clients: dict[str, httpx.AsyncClient] = {}
        self._acting_email: str = _VISITOR

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._bg.start()

    def stop(self) -> None:
        self._close_clients()
        self._bg.stop()

    def run(self, coro):
        return self._bg.run(coro)

    def make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            follow_redirects=False,
        )

    @property
    def client(self) -> httpx.AsyncClient:
        return self.client_for(self._acting_email)

    def _close_clients(self) -> None:
        for c in self._clients.values():
            self._bg.run(c.aclose())
        self._clients = {}

    def reset_session(self) -> None:
        self._close_clients()
        self._acting_email = _VISITOR

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        db._test_connection = self.run(db.begin_test_transaction(_admin_engine()))
        app.dependency_overrides[get_user_session] = db.override_get_session
        app.dependency_overrides[get_admin_session] = db.override_get_session
        app.dependency_overrides[get_rls_session] = db.override_get_rls_session

    def teardown_test(self) -> None:
        """Roll back the test transaction, then clean up data committed outside it."""
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_rls_session, None)
        conn = db._test_connection
        db._test_connection = None
        if conn is not None:
            self.run(db.end_test_transaction(conn))
        self.cleanup_committed_data()
        self._cleanup_auth_users()

    def cleanup_committed_data(self) -> None:
        """Hook: feature mixins override to delete data committed outside the transaction."""

    # ── JSON (REST) calls ──────────────────────────────────────────────────────
    def json_client(self, method: str, path: str, client: httpx.AsyncClient | None = None, **kw):
        headers = {"accept": "application/json", **kw.pop("headers", {})}
        return self.run((client or self.client).request(method, path, headers=headers, **kw))

    # ── auth user tracking ─────────────────────────────────────────────────────
    # Supabase auth users live outside the rolled-back transaction; tracked here
    # and deleted in teardown.
    def track_auth_email(self, email: str) -> None:
        if email not in self._test_auth_emails:
            self._test_auth_emails.append(email)

    def _cleanup_auth_users(self) -> None:
        for email in self._test_auth_emails:
            delete_user_if_exists(email)
        self._test_auth_emails.clear()

    # ── unified multi-user client management ───────────────────────────────────
    # All clients live in a single dict keyed by email (or _VISITOR for the
    # unauthenticated client). self.client always returns the acting user's client.
    def client_for(self, email: str) -> httpx.AsyncClient:
        if email not in self._clients:
            if email == _VISITOR:
                self._clients[email] = self.make_client()
            else:
                client = self.make_client()
                creds = {"email": email, "password": _PASSWORD}
                self.json_client("POST", "/auth/register", client=client, json=creds)
                self.json_client("POST", "/auth/login", client=client, json=creds)
                self.track_auth_email(email)
                self._clients[email] = client
        return self._clients[email]

    def set_acting_email(self, email: str) -> None:
        """Adopt `email` as the acting user, re-keying the visitor session if needed."""
        if _VISITOR in self._clients and email not in self._clients:
            self._clients[email] = self._clients.pop(_VISITOR)
        self._acting_email = email

    def clear_acting_email(self) -> None:
        self._acting_email = _VISITOR

    def user_id_for_email(self, email: str) -> str:
        users = find_users(email)
        assert users, f"User {email!r} not found in Supabase"
        return users[0].id
