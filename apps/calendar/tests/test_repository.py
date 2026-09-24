"""`CalendarEventRepository.upcoming`'s bound, run against a real, RLS-enforcing session.

The dashboard overview needs an org's soonest upcoming events without loading every future one
it has — this holds `upcoming`'s contract (past events excluded, bounded, ordered by start
time rather than by creation order) in isolation from the overview that calls it.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import tests.e2e.clock as test_clock
from apps.auth.tests.given_helpers import create_user, delete_user
from apps.calendar.infra.repository import CalendarEventRepository
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared import clock
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
async def test_upcoming_orders_by_start_time_not_by_creation_order(db_session: AsyncSession):
    """Inserted out of chronological order, so a query that ordered by id (mint order) or by
    insertion order instead of `starts_at` would return a different, wrong pair."""
    test_clock.set_current_date("2024-06-01")
    async with _an_org(db_session) as (org_id, owner_id):
        repo = CalendarEventRepository(db_session, org_id)
        now = clock.now()
        await repo.add(owner_id, "Past", now - timedelta(days=1), now - timedelta(hours=23))
        await repo.add(
            owner_id, "Latest", now + timedelta(days=2), now + timedelta(days=2, hours=1)
        )
        await repo.add(owner_id, "Soonest", now + timedelta(hours=1), now + timedelta(hours=2))
        await repo.add(
            owner_id, "Middle", now + timedelta(days=1), now + timedelta(days=1, hours=1)
        )

        recent = await repo.upcoming(now, 2)

    assert [e.title for e in recent] == ["Soonest", "Middle"]
