"""`OrgFileRepository`'s bounded read, run directly against a real, RLS-enforcing session.

The dashboard overview needs an org's most recent files without loading every one of them —
this holds `OrgScopedRepository.recent`'s contract (bounded, newest first) for a repository
other than the one it was first written for, so a shared implementation is what every caller
gets, not a copy some of them missed.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import tests.e2e.clock as test_clock
from apps.auth.tests.given_helpers import create_user, delete_user
from apps.files.infra.repository import OrgFileRepository
from apps.files.infra.storage import storage_path
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as


@asynccontextmanager
async def _an_org(session: AsyncSession) -> AsyncGenerator[uuid.UUID]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
                yield org.id
        finally:
            await outer.rollback()
    finally:
        delete_user(owner)


@pytest.mark.asyncio
async def test_recent_returns_only_the_newest_files_up_to_the_limit(db_session: AsyncSession):
    uploader = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        async with _an_org(db_session) as org_id:
            repo = OrgFileRepository(db_session, org_id)
            test_clock.set_current_date("2024-01-01")
            for filename in ("oldest.txt", "middle.txt", "newest.txt"):
                file_id = uuid.uuid7()
                await repo.add(
                    file_id=file_id,
                    uploaded_by=uuid.UUID(uploader),
                    filename=filename,
                    storage_path=storage_path(org_id, file_id, filename),
                    content_type="text/plain",
                    size_bytes=1,
                )
                test_clock.advance_days(1)

            recent = await repo.recent(2)
    finally:
        delete_user(uploader)

    assert [f.filename for f in recent] == ["newest.txt", "middle.txt"]
