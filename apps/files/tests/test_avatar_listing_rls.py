"""Avatars share the ``org-files`` bucket under ``avatars/{user_id}.{ext}`` — a path whose first
segment is never an org id. Every storage policy casts that segment to uuid to scope the row by
org, so once an avatar object exists, a user-scoped read of the bucket has to evaluate that row
too, and the cast must not raise on it.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.persistence.storage import bucket
from tests.rls import acting_as

_INSERT_OBJECT = text(
    "insert into storage.objects (bucket_id, name) values (:bucket, :name) returning id"
)
_LIST_OBJECTS = text("select id from storage.objects where bucket_id = :bucket")


@dataclass(frozen=True)
class OrgFileAndAvatar:
    member: str
    org_object_id: uuid.UUID


@asynccontextmanager
async def _an_org_object_and_an_avatar_object(
    session: AsyncSession,
) -> AsyncGenerator[OrgFileAndAvatar]:
    member = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, member):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(member)
                )
            # Seeded on the bootstrap (superuser) role: an insert under RLS would hit the
            # same cast this test is about, in the policy's WITH CHECK.
            org_object_id = await session.scalar(
                _INSERT_OBJECT, {"bucket": bucket(), "name": f"{org.id}/notes.txt"}
            )
            await session.execute(
                _INSERT_OBJECT, {"bucket": bucket(), "name": f"avatars/{uuid.uuid4()}.png"}
            )
            yield OrgFileAndAvatar(member=member, org_object_id=org_object_id)
        finally:
            await outer.rollback()
    finally:
        delete_user(member)


@pytest.mark.asyncio
async def test_a_member_lists_the_bucket_without_the_avatar_cast_raising(
    db_session: AsyncSession,
):
    async with (
        _an_org_object_and_an_avatar_object(db_session) as seeded,
        acting_as(db_session, seeded.member),
        db_session.begin_nested(),
    ):
        visible = set(await db_session.scalars(_LIST_OBJECTS, {"bucket": bucket()}))

    assert visible == {seeded.org_object_id}
