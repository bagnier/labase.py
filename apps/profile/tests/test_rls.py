"""Proof that RLS protects profiles: even without an application filter,
a user only sees their own profile via the authenticated role.
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.tests.given_helpers import create_user, delete_user
from apps.profile.domain.models import Profile
from apps.shared.persistence.rls import set_rls_context


@pytest.mark.asyncio
async def test_rls_profile_isolation(db_session: AsyncSession):
    email1 = f"{uuid.uuid4()}@rls.local"
    email2 = f"{uuid.uuid4()}@rls.local"
    uid1_str = create_user(email1, "Test1234!")
    uid2_str = create_user(email2, "Test1234!")
    try:
        await set_rls_context(db_session, uuid.UUID(uid1_str))
        result = await db_session.execute(select(Profile))
        profiles = list(result.scalars().all())

        assert len(profiles) == 1, f"RLS should limit to 1 profile (user1), got {len(profiles)}"
        assert profiles[0].auth_user_id == uuid.UUID(uid1_str)
    finally:
        delete_user(uid1_str)
        delete_user(uid2_str)
