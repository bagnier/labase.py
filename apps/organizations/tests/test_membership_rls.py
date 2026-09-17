"""Ownership is only ever handed out by an owner, or at an org's creation.

Driven the way a PostgREST client holding its own JWT would: raw SQL on the ``authenticated``
session, bypassing the routes.
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
from apps.organizations.domain.models import OrgRole
from apps.organizations.infra.repository import OrganizationRepository
from tests.rls import acting_as


@dataclass(frozen=True)
class Org:
    owner: str
    stranger: str
    org_id: uuid.UUID


@asynccontextmanager
async def _an_org_and_a_stranger(session: AsyncSession) -> AsyncGenerator[Org]:
    owner = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    stranger = create_user(f"{uuid.uuid4()}@rls.local", "Test1234!")
    try:
        # Rolled back before delete_user, so the FK locks on auth.users are released.
        outer = await session.begin_nested()
        try:
            async with acting_as(session, owner):
                org = await OrganizationRepository(session).create_with_owner(
                    f"Org {uuid.uuid4().hex[:8]}", uuid.UUID(owner)
                )
            yield Org(owner=owner, stranger=stranger, org_id=org.id)
        finally:
            await outer.rollback()
    finally:
        delete_user(owner)
        delete_user(stranger)


@pytest.mark.asyncio
async def test_creating_an_org_makes_its_creator_the_owner(db_session: AsyncSession):
    async with _an_org_and_a_stranger(db_session) as org, acting_as(db_session, org.owner):
        membership = await OrganizationRepository(db_session).get_membership(
            org.org_id, uuid.UUID(org.owner)
        )
        role = membership.role if membership else None

    assert role == OrgRole.owner


@pytest.mark.asyncio
async def test_a_stranger_cannot_make_themselves_owner_of_an_existing_org(
    db_session: AsyncSession,
):
    async with _an_org_and_a_stranger(db_session) as org, acting_as(db_session, org.stranger):
        with pytest.raises(ProgrammingError, match="row-level security"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text(
                        "insert into memberships (org_id, user_id, role)"
                        " values (:org_id, :user_id, 'owner')"
                    ),
                    {"org_id": org.org_id, "user_id": org.stranger},
                )


@pytest.mark.asyncio
async def test_an_org_cannot_be_created_without_its_owner(db_session: AsyncSession):
    async with _an_org_and_a_stranger(db_session) as org, acting_as(db_session, org.stranger):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with db_session.begin_nested():
                await db_session.execute(
                    text("insert into organizations (name, handle) values ('Orphan', :handle)"),
                    {"handle": f"orphan-{uuid.uuid4().hex[:8]}"},
                )
