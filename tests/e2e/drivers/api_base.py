"""The API driver's base: event loop, one client per user, rolled-back test transaction."""

from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import delete_user_if_exists
from apps.main import host
from apps.shared.events.listener import EventListener
from apps.shared.persistence.database import (
    _admin_engine,
    get_admin_session,
    get_user_session,
)
from apps.shared.queue import TaskWorker
from tests.e2e.drivers import api_transaction as db
from tests.e2e.drivers.async_runner import AsyncRunner
from tests.e2e.drivers.conformance import Conformance
from tests.e2e.drivers.transport import ASGISyncTransport

_conformance = Conformance(host.app.openapi())

app = host.app

_T = TypeVar("_T")
_PASSWORD = "Secret1!"
VISITOR = "visitor"  # the unauthenticated client


class ApiBase:
    # Every seeded user's password, so a scenario naming a user can omit it.
    PASSWORD = _PASSWORD

    def __init__(self) -> None:
        self._runner = AsyncRunner()
        self._test_auth_emails: list[str] = []
        self._clients: dict[str, httpx.Client] = {}
        self._acting_email: str = VISITOR
        self._response: httpx.Response | None = None

    @property
    def response(self) -> httpx.Response:
        """The last response; raises if none yet (a broken scenario). Read ``_response`` to ask
        whether a request happened."""
        if self._response is None:
            raise AssertionError("No response stored — the scenario asserted before requesting")
        return self._response

    @response.setter
    def response(self, response: httpx.Response) -> None:
        self._response = response

    # ── shared access-control assertions (phrases live in tests/e2e/steps_common) ─
    def assert_forbidden(self) -> None:
        assert self.response.status_code == 403, (
            f"Expected 403, got {self.response.status_code}: {self.response.text}"
        )

    def assert_not_found(self) -> None:
        assert self.response.status_code == 404, (
            f"Expected 404, got {self.response.status_code}: {self.response.text}"
        )

    # ── lifecycle ──────────────────────────────────────────────────────────────
    def start(self) -> None:
        """Nothing to start: the loop runs from construction."""

    def stop(self) -> None:
        self._close_clients()
        self._runner.stop()

    def run(self, coro: Coroutine[Any, Any, _T]) -> _T:
        return self._runner.run(coro)

    def _make_client(self) -> httpx.Client:
        # Every JSON answer is checked against its route's schema (see ``conformance``).
        return httpx.Client(
            transport=ASGISyncTransport(self._runner),
            base_url="http://testserver",
            follow_redirects=False,
            headers={"accept": "application/json"},
            event_hooks={"response": [_conformance.check]},
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
        self._response = None

    # ── test isolation ─────────────────────────────────────────────────────────
    def setup_test(self) -> None:
        db._test_connection = self.run(db.begin_test_transaction(_admin_engine()))
        app.dependency_overrides[get_user_session] = db.override_get_session
        app.dependency_overrides[get_admin_session] = db.override_get_session

    def teardown_test(self) -> None:
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_admin_session, None)
        conn = db._test_connection
        db._test_connection = None
        if conn is not None:
            self.run(db.end_test_transaction(conn))
        self._cleanup_committed_data()
        self._cleanup_auth_users()

    def _cleanup_committed_data(self) -> None:
        """Mixins delete here what they committed outside the transaction."""

    def test_session_factory(self) -> Callable[[], AsyncSession]:
        """Sessions on the test connection, to drive the background loops (off under tests) on
        what a request just wrote."""
        return db.session_on_test_connection

    def drain_task_queue(self) -> None:
        """Run the listener and the worker until both are dry, so reactions (and the facts they
        emit) are done. The loops are off under tests."""
        factory = self.test_session_factory()
        listener = EventListener(0, session_factory=factory)
        worker = TaskWorker(0, session_factory=factory)
        while True:
            fanned = self.run(listener.tick())
            processed = 0
            while self.run(worker.tick()):
                processed += 1
            if not fanned and not processed:
                break

    # ── auth user tracking ─────────────────────────────────────────────────────
    def _track_auth_email(self, email: str) -> None:
        if email not in self._test_auth_emails:
            self._test_auth_emails.append(email)

    def _cleanup_auth_users(self) -> None:
        # GoTrue escapes the rollback: ``delete_user`` also sweeps the user's facts.
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
                # UserCreated's reactions before login, so the JWT carries any admin role.
                self.drain_task_queue()
                client.post("/auth/login", json=creds)
                self._track_auth_email(email)
            self._clients[email] = client
        return self._clients[email]

    def set_acting_email(self, email: str) -> None:
        if VISITOR in self._clients and email not in self._clients:
            self._clients[email] = self._clients.pop(VISITOR)
        self._acting_email = email

    def adopt_current_client(self, email: str) -> None:
        """Key the client that just signed in under `email`, replacing a stale one."""
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
        """After an email change: the same cookies, under the new email."""
        old = self._acting_email
        if old != email and old in self._clients and email not in self._clients:
            self._clients[email] = self._clients.pop(old)
        self._acting_email = email

    def clear_acting_email(self) -> None:
        self._acting_email = VISITOR
