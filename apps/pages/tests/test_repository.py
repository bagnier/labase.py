"""`PageRepository`'s bounded read, run directly against a real, RLS-enforcing session.

The dashboard overview needs an org's most recent pages without loading every one of them —
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
from apps.organizations.infra.repository import OrganizationRepository
from apps.pages.infra.repository import PageRepository
from tests.rls import acting_as


@asynccontextmanager
async def _an_org(session: AsyncSession) -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID]]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
                yield org.id, uuid.UUID(owner)
        finally:
            await outer.rollback()
    finally:
        delete_user(owner)


@pytest.mark.asyncio
async def test_recent_returns_only_the_newest_pages_up_to_the_limit(db_session: AsyncSession):
    async with _an_org(db_session) as (org_id, owner_id):
        repo = PageRepository(db_session, org_id)
        test_clock.set_current_date("2024-01-01")
        for slug in ("oldest", "middle", "newest"):
            await repo.add(owner_id, slug.title(), slug, "")
            test_clock.advance_days(1)

        recent = await repo.recent(2)

    assert [p.title for p in recent] == ["Newest", "Middle"]
