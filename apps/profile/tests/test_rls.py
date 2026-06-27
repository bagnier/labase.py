"""Proof that RLS protects profiles: even without an application filter,
a user only sees their own profile via the authenticated role.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.profile.domain.models import Profile
from tests.rls import assert_rls_isolation


@pytest.mark.asyncio
async def test_rls_profile_isolation(db_session: AsyncSession):
    email1 = f"{uuid.uuid4()}@rls.local"
    email2 = f"{uuid.uuid4()}@rls.local"
    uid1 = create_user(email1, "Test1234!")
    uid2 = create_user(email2, "Test1234!")
    try:
        id_query = select(Profile.auth_user_id)
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
