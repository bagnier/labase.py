"""Technical substrate for API tests: event loop, unified multi-user client
management, rolled-back test transaction.
Feature mixins inherit this; ApiDriver assembles them."""

from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx

from apps.auth.infra.session import get_rls_session
from apps.auth.tests.given_helpers import delete_user_if_exists
from apps.main import host
from apps.shared.persistence.database import (
    _admin_engine,
    get_admin_session,
    get_user_session,
)
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.async_runner import AsyncRunner
from tests.e2e.drivers.transport import ASGISyncTransport

app = host.app

_T = TypeVar("_T")
_PASSWORD = "Secret1!"
VISITOR = "visitor"  # sentinel — unauthenticated client, no associated user


class ApiBase:
    def __init__(self) -> None:
        self._runner = AsyncRunner()
        self._test_auth_emails: list[str] = []
        self._clients: dict[str, httpx.Client] = {}
        self._acting_email: str = VISITOR

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        self._runner.start()

    def stop(self) -> None:
        self._close_clients()
        self._runner.stop()

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self._runner.run(coro)

    def _make_client(self) -> httpx.Client:
        return httpx.Client(
            transport=ASGISyncTransport(self._runner),
            base_url="http://testserver",
            follow_redirects=False,
            headers={"accept": "application/json"},
        )

    def client(self) -> httpx.Client:
        return self.client_for(self._acting_email)

    def _close_clients(self) -> None:
        for client in self._clients.values():
            client.close()
        self._clients = {}

    def reset_session(self) -> None:
        self._close_clients()
        self._acting_email = VISITOR

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
        self._cleanup_committed_data()
        self._cleanup_auth_users()

    def _cleanup_committed_data(self) -> None:
        """Hook: feature mixins override to delete data committed outside the transaction."""

    # ── auth user tracking ─────────────────────────────────────────────────────
    def _track_auth_email(self, email: str) -> None:
        if email not in self._test_auth_emails:
            self._test_auth_emails.append(email)

    def _cleanup_auth_users(self) -> None:
        for email in self._test_auth_emails:
            delete_user_if_exists(email)
        self._test_auth_emails.clear()

    # ── unified multi-user client management ───────────────────────────────────
    def client_for(self, email: str) -> httpx.Client:
        if email not in self._clients:
            client = self._make_client()
            if email != VISITOR:
                creds = {"email": email, "password": _PASSWORD}
                client.post("/auth/register", json=creds)
                client.post("/auth/login", json=creds)
                self._track_auth_email(email)
            self._clients[email] = client
        return self._clients[email]

    def set_acting_email(self, email: str) -> None:
        """Adopt `email` as the acting user, promoting the visitor session if one exists."""
        if VISITOR in self._clients and email not in self._clients:
            self._clients[email] = self._clients.pop(VISITOR)
        self._acting_email = email

    def clear_acting_email(self) -> None:
        self._acting_email = VISITOR
