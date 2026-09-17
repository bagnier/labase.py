"""A share token is the download gate, so RLS scopes it to the members of the file's org.

The foreign key only proves the file exists — it is checked without RLS — so these tests drive
the table the way a PostgREST client holding its own JWT would: raw SQL on the ``authenticated``
session, bypassing the route that looks the file up first.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.files.infra.repository import OrgFileRepository
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as

_INSERT_TOKEN = text(
    "insert into org_file_share_tokens (file_id, expires_at)"
    " values (:file_id, now() + interval '1 day') returning token"
)
_TOKENS_OF_FILE = text("select token from org_file_share_tokens where file_id = :file_id")


@dataclass(frozen=True)
class SharedFile:
    member: str
    stranger: str
    file_id: uuid.UUID


@asynccontextmanager
async def _a_file_and_a_stranger(session: AsyncSession) -> AsyncGenerator[SharedFile]:
    member = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    stranger = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, member):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(member)
                )
                org_file = await OrgFileRepository(session, org.id).add(
                    uuid.UUID(member), "secret.txt", f"{org.id}/secret.txt", "text/plain", 6
                )
            yield SharedFile(member=member, stranger=stranger, file_id=org_file.id)
        finally:
            await outer.rollback()
    finally:
        delete_user(member)
        delete_user(stranger)


@pytest.mark.asyncio
async def test_a_member_shares_a_file_of_their_org(db_session: AsyncSession):
    async with (
        _a_file_and_a_stranger(db_session) as shared,
        acting_as(db_session, shared.member),
    ):
        token = await db_session.scalar(_INSERT_TOKEN, {"file_id": shared.file_id})
        visible = set(await db_session.scalars(_TOKENS_OF_FILE, {"file_id": shared.file_id}))

    assert visible == {token}


@pytest.mark.asyncio
async def test_a_stranger_cannot_share_a_file_of_another_org(db_session: AsyncSession):
    async with (
        _a_file_and_a_stranger(db_session) as shared,
        acting_as(db_session, shared.stranger),
    ):
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with db_session.begin_nested():
                await db_session.execute(_INSERT_TOKEN, {"file_id": shared.file_id})


@pytest.mark.asyncio
async def test_a_stranger_cannot_read_the_share_tokens_of_another_org(db_session: AsyncSession):
    async with _a_file_and_a_stranger(db_session) as shared:
        async with acting_as(db_session, shared.member):
            await db_session.execute(_INSERT_TOKEN, {"file_id": shared.file_id})
        async with acting_as(db_session, shared.stranger):
            visible = set(await db_session.scalars(_TOKENS_OF_FILE, {"file_id": shared.file_id}))

    assert visible == set()
