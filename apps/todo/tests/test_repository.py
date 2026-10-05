"""`TodoRepository.recent_open`: bounded, done tasks skipped, by `position`."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.infra.repository import OrganizationRepository
from apps.todo.infra.repository import TodoRepository
from tests.rls import acting_as


@asynccontextmanager
async def _an_org(session: AsyncSession) -> AsyncGenerator[tuple[uuid.UUID, uuid.UUID]]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, releasing the FK locks.
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
async def test_recent_open_orders_by_position_not_by_creation_order(db_session: AsyncSession):
    """`oldest` is moved to the top, so ordering by id would fail."""
    async with _an_org(db_session) as (org_id, owner_id):
        repo = TodoRepository(db_session, org_id)
        oldest = await repo.add(owner_id, "Oldest")
        await repo.add(owner_id, "Middle")
        closed = await repo.add(owner_id, "Closed")
        newest = await repo.add(owner_id, "Newest")
        closed.done = True
        await repo.move_above(oldest.id, newest.id)

        recent = await repo.recent_open(2)

    assert [t.title for t in recent] == ["Oldest", "Newest"]
