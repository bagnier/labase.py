import asyncio
import threading
import uuid

import httpx
from sqlalchemy import delete

from app.auth.infra.session import get_rls_session
from app.auth.tests.driver_mixin import AuthApiMixin
from app.console.tests.driver_mixin import ConsoleApiMixin
from app.files.tests.driver_mixin import OrgFileApiMixin
from app.learning.tests.driver_mixin import LearningApiMixin
from app.main import app
from app.organizations.domain.models import Organization
from app.organizations.tests.driver_mixin import OrgApiMixin
from app.profile.tests.driver_mixin import ProfileApiMixin
from app.shared.persistence.database import (
    _admin_engine,
    admin_session_factory,
    get_admin_session,
    get_user_session,
)
from app.todo.tests.driver_mixin import TodoApiMixin
from tests import db
from tests.e2e.drivers.shared_mixin import SharedApiMixin


class ApiDriver(
    AuthApiMixin,
    ConsoleApiMixin,
    ProfileApiMixin,
    TodoApiMixin,
    LearningApiMixin,
    OrgFileApiMixin,
    OrgApiMixin,
    SharedApiMixin,
):
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None
        self._response: httpx.Response | None = None
        self._last_registered_email: str | None = None
        self._test_auth_emails: list[str] = []
        self._test_org_ids: list[str] = []
        self._test_conn = None

    def setup_test(self) -> None:
        """Open the rolled-back test transaction and route all sessions onto it."""
        conn = self._run(db.begin_test_transaction(_admin_engine()))
        db._test_connection = conn
        self._test_conn = conn
        app.dependency_overrides[get_user_session] = db.override_get_session
        app.dependency_overrides[get_admin_session] = db.override_get_session
        app.dependency_overrides[get_rls_session] = db.override_get_rls_session

    def teardown_test(self) -> None:
        """Roll back the test transaction and clean up out-of-transaction data."""
        app.dependency_overrides.pop(get_user_session, None)
        app.dependency_overrides.pop(get_admin_session, None)
        app.dependency_overrides.pop(get_rls_session, None)
        db._test_connection = None
        self._restore_clock()
        self._run(db.end_test_transaction(self._test_conn))
        self._test_conn = None
        self.cleanup_test_orgs()
        self.cleanup_test_auth_users()

    def start(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )

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

    @property
    def _c(self) -> httpx.AsyncClient:
        assert self._client
        return self._client

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

    def reset_session(self) -> None:
        transport = httpx.ASGITransport(app=app)
        self._client = httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=False,
        )
        self._reset_multi_user_state()
