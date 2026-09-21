"""Proof that RLS protects profiles: even without an application filter, a user sees their own
profile and those of the people they share an org with, via the authenticated role.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.profile.domain.models import Profile
from tests.authorization import an_org_in_db
from tests.rls import assert_rls_isolation


@pytest.mark.asyncio
async def test_rls_profile_isolation(db_session: AsyncSession):
    email1 = f"{uuid.uuid4()}@rls.local"
    email2 = f"{uuid.uuid4()}@rls.local"
    uid1 = create_user(email1, "Test1234!")
    uid2 = create_user(email2, "Test1234!")
    try:
        id_query = select(Profile.user_id)
        # Each user sees their own profile row and never the other's.
        await assert_rls_isolation(
            db_session, id_query, item=uuid.UUID(uid1), visible_to=uid1, hidden_from=[uid2]
        )
        await assert_rls_isolation(
            db_session, id_query, item=uuid.UUID(uid2), visible_to=uid2, hidden_from=[uid1]
        )
    finally:
        delete_user(uid1)
        delete_user(uid2)


@pytest.mark.asyncio
async def test_rls_profile_is_read_by_co_members_not_by_outsiders(db_session: AsyncSession):
    """Their avatars appear next to each other: sharing an org is what opens a profile, and
    nothing else does."""
    async with an_org_in_db(db_session) as org:
        await assert_rls_isolation(
            db_session,
            select(Profile.user_id),
            item=uuid.UUID(org.people["member"]),
            visible_to=org.people["other"],
            hidden_from=[org.people["outsider"]],
        )
