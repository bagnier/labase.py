"""Drafts are collaborative; publishing, changing a published page and the navigation are the
owners'. Held by RLS, and driven the way a member's PostgREST client would reach it."""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as, as_api_client

_INSERT_PAGE = text(
    "insert into pages (org_id, user_id, title, slug, visibility)"
    " values (:org_id, :user_id, 'T', :slug, CAST(:visibility AS page_visibility))"
    " returning id"
)
_RETITLE = text("update pages set title = 'Changed' where id = :page_id returning id")
_DELETE = text("delete from pages where id = :page_id returning id")


@dataclass(frozen=True)
class Org:
    owner: str
    member: str
    org_id: uuid.UUID
    draft_id: uuid.UUID
    published_id: uuid.UUID


@asynccontextmanager
async def _an_org_with_a_member(session: AsyncSession) -> AsyncGenerator[Org]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    member = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
                await session.execute(
                    text("insert into memberships (org_id, user_id) values (:org_id, :user_id)"),
                    {"org_id": org.id, "user_id": member},
                )
                ids = {
                    visibility: await session.scalar(
                        _INSERT_PAGE,
                        {
                            "org_id": org.id,
                            "user_id": owner,
                            "slug": visibility,
                            "visibility": visibility,
                        },
                    )
                    for visibility in ("draft", "public")
                }
            yield Org(owner, member, org.id, ids["draft"], ids["public"])
        finally:
            await outer.rollback()
    finally:
        delete_user(owner)
        delete_user(member)


async def _as_member(session: AsyncSession, org: Org, statement, **params) -> set:
    async with as_api_client(session, org.member):
        return set(await session.scalars(statement, params))


@pytest.mark.asyncio
async def test_a_member_edits_a_draft(db_session: AsyncSession):
    async with _an_org_with_a_member(db_session) as org:
        changed = await _as_member(db_session, org, _RETITLE, page_id=org.draft_id)

    assert changed == {org.draft_id}


@pytest.mark.asyncio
async def test_a_member_cannot_publish_a_page(db_session: AsyncSession):
    async with _an_org_with_a_member(db_session) as org, as_api_client(db_session, org.member):
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with db_session.begin_nested():
                await db_session.execute(
                    _INSERT_PAGE,
                    {
                        "org_id": org.org_id,
                        "user_id": org.member,
                        "slug": "leak",
                        "visibility": "public",
                    },
                )


@pytest.mark.asyncio
async def test_a_member_cannot_change_a_published_page(db_session: AsyncSession):
    async with _an_org_with_a_member(db_session) as org:
        changed = await _as_member(db_session, org, _RETITLE, page_id=org.published_id)

    assert changed == set()


@pytest.mark.asyncio
async def test_a_member_cannot_delete_a_published_page(db_session: AsyncSession):
    async with _an_org_with_a_member(db_session) as org:
        deleted = await _as_member(db_session, org, _DELETE, page_id=org.published_id)

    assert deleted == set()


@pytest.mark.asyncio
async def test_a_member_cannot_put_a_page_in_the_navigation(db_session: AsyncSession):
    async with _an_org_with_a_member(db_session) as org, as_api_client(db_session, org.member):
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text("insert into page_nav_items (org_id, page_id) values (:org_id, :page)"),
                    {"org_id": org.org_id, "page": org.published_id},
                )
