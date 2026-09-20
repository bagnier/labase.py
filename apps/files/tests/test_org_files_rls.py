"""A file row names only its own object, and only its uploader or an owner changes it.

The share link and the download sign ``storage_path`` with the service key, so a path the row does
not own would serve another org's bytes. Driven the way a member's PostgREST client would.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.files.infra.repository import OrgFileRepository
from apps.files.infra.storage import storage_path
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as, as_api_client

_SET_PATH = text("update org_files set storage_path = :path where id = :file_id returning id")
_RENAME = text("update org_files set filename = 'renamed.txt' where id = :file_id returning id")
_DELETE = text("delete from org_files where id = :file_id returning id")


@dataclass(frozen=True)
class OrgFiles:
    owner: str
    uploader: str
    member: str
    org_id: uuid.UUID
    file_id: uuid.UUID


@asynccontextmanager
async def _a_file_uploaded_by_a_member(session: AsyncSession) -> AsyncGenerator[OrgFiles]:
    owner, uploader, member = (
        create_user(f"{uuid.uuid4()}@rls.local", "Test1234!") for _ in range(3)
    )
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
                for user in (uploader, member):
                    await session.execute(
                        text("insert into memberships (org_id, user_id) values (:org, :user)"),
                        {"org": org.id, "user": user},
                    )
            async with acting_as(session, uploader):
                file_id = uuid.uuid7()
                await OrgFileRepository(session, org.id).add(
                    file_id,
                    uuid.UUID(uploader),
                    "notes.txt",
                    storage_path(org.id, file_id, "notes.txt"),
                    "text/plain",
                    5,
                )
            yield OrgFiles(owner, uploader, member, org.id, file_id)
        finally:
            await outer.rollback()
    finally:
        for user in (owner, uploader, member):
            delete_user(user)


async def _as(session: AsyncSession, uid: str, statement, **params) -> set:
    async with as_api_client(session, uid):
        return set(await session.scalars(statement, params))


@pytest.mark.asyncio
async def test_a_file_row_cannot_name_an_object_outside_its_own_path(db_session: AsyncSession):
    foreign = f"{uuid.uuid4()}/{uuid.uuid4()}_secret.pdf"
    async with (
        _a_file_uploaded_by_a_member(db_session) as files,
        as_api_client(db_session, files.uploader),
    ):
        with pytest.raises(IntegrityError, match="check constraint"):
            async with db_session.begin_nested():
                await db_session.execute(_SET_PATH, {"path": foreign, "file_id": files.file_id})


@pytest.mark.asyncio
async def test_a_renamed_file_keeps_a_path_of_its_own(db_session: AsyncSession):
    async with _a_file_uploaded_by_a_member(db_session) as files:
        path = storage_path(files.org_id, files.file_id, "renamed.txt")
        changed = await _as(db_session, files.uploader, _SET_PATH, path=path, file_id=files.file_id)

    assert changed == {files.file_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", [_RENAME, _DELETE])
async def test_another_member_cannot_change_a_file(db_session: AsyncSession, statement):
    async with _a_file_uploaded_by_a_member(db_session) as files:
        changed = await _as(db_session, files.member, statement, file_id=files.file_id)

    assert changed == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("statement", [_RENAME, _DELETE])
async def test_an_owner_changes_a_members_file(db_session: AsyncSession, statement):
    async with _a_file_uploaded_by_a_member(db_session) as files:
        changed = await _as(db_session, files.owner, statement, file_id=files.file_id)

    assert changed == {files.file_id}


@pytest.mark.asyncio
async def test_the_uploader_deletes_their_file(db_session: AsyncSession):
    async with _a_file_uploaded_by_a_member(db_session) as files:
        deleted = await _as(db_session, files.uploader, _DELETE, file_id=files.file_id)

    assert deleted == {files.file_id}
