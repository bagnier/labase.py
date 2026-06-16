import asyncio
import threading
import uuid

import httpx
from sqlalchemy import delete

from app.auth.tests.driver_mixin import AuthApiMixin
from app.console.tests.driver_mixin import ConsoleApiMixin
from app.files.tests.driver_mixin import OrgFileApiMixin
from app.learning.tests.driver_mixin import LearningApiMixin
from app.main import app
from app.organizations.domain.models import Organization
from app.organizations.tests.driver_mixin import OrgApiMixin
from app.profile.tests.driver_mixin import ProfileApiMixin
from app.shared.persistence.database import admin_session_factory
from app.todo.tests.driver_mixin import TodoApiMixin
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
