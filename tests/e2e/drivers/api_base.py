"""Technical substrate for API tests: event loop, unified multi-user client
management, rolled-back test transaction.
Feature mixins inherit this; ApiDriver assembles them."""

from collections.abc import Coroutine
from typing import Any, TypeVar

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.infra.session import get_rls_session
from apps.auth.tests.given_helpers import delete_user_if_exists
from apps.main import host
from apps.shared.persistence.database import (
    _admin_engine,
    get_admin_session,
    get_user_session,
)
from apps.shared.queue import TaskWorker
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.async_runner import AsyncRunner
from tests.e2e.drivers.transport import ASGISyncTransport

app = host.app

_T = TypeVar("_T")
_PASSWORD = "Secret1!"
VISITOR = "visitor"  # sentinel — unauthenticated client, no associated user


class ApiBase:
    # Canonical e2e password. client_for() re-authenticates every seeded email
    # with it, so a scenario that only *names* a user (no auth intent) can omit
    # the password and rely on this default.
    PASSWORD = _PASSWORD

    def __init__(self) -> None:
        self._runner = AsyncRunner()
        self._test_auth_emails: list[str] = []
        self._clients: dict[str, httpx.Client] = {}
        self._acting_email: str = VISITOR
        self.response: httpx.Response | None = None

    # ── shared access-control assertions (phrases live in tests/e2e/steps_common) ─
    def assert_forbidden(self) -> None:
        assert self.response is not None, "No response stored — cannot check forbidden"
        assert self.response.status_code == 403, (
            f"Expected 403, got {self.response.status_code}: {self.response.text}"
        )

    def assert_not_found(self) -> None:
        assert self.response is not None, "No response stored — cannot check not-found"
        assert self.response.status_code == 404, (
            f"Expected 404, got {self.response.status_code}: {self.response.text}"
        )

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

    def drain_task_queue(self) -> None:
        """Deliver queued tasks (e.g. outboxed email) now.

        The polling worker is off under tests — and could not see the rolled-back
        test transaction anyway, so the tick runs on the test connection itself.
        """
        assert db._test_connection is not None, "No active test transaction"
        worker = TaskWorker(
            0,
            session_factory=lambda: AsyncSession(bind=db._test_connection, expire_on_commit=False),
        )
        while self.run(worker.tick()):
            pass

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

    def adopt_current_client(self, email: str) -> None:
        """The acting (visitor) client just authenticated as `email`: key it under
        that identity, replacing any stale client left from an earlier session."""
        old = self._acting_email
        if old == email or old not in self._clients:
            self._acting_email = email
            return
        stale = self._clients.pop(email, None)
        if stale is not None:
            stale.close()
        self._clients[email] = self._clients.pop(old)
        self._acting_email = email

    def rekey_acting_identity(self, email: str) -> None:
        """The acting user changed identity in place (e.g. confirmed an email change):
        their live session keeps its cookies but now answers to the new email."""
        old = self._acting_email
        if old != email and old in self._clients and email not in self._clients:
            self._clients[email] = self._clients.pop(old)
        self._acting_email = email

    def clear_acting_email(self) -> None:
        self._acting_email = VISITOR
