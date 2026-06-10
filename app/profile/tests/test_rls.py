"""
Preuve que le RLS protège les profils : même sans filtre applicatif,
un utilisateur ne voit que son propre profil via le rôle authenticated.
"""

import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.auth.tests.admin_helpers import create_user, delete_user
from app.profile.domain.models import Profile
from app.shared.config import get_settings


@pytest.mark.asyncio
async def test_rls_profile_isolation():
    settings = get_settings()
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(
        settings.database_url_service or settings.database_url,
        echo=False,
        connect_args=connect_args,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    email1 = f"{uuid.uuid4()}@rls.local"
    email2 = f"{uuid.uuid4()}@rls.local"
    uid1_str = create_user(email1, "Test1234!")
    uid2_str = create_user(email2, "Test1234!")
    uid1 = uuid.UUID(uid1_str)
    try:
        claims = json.dumps({"sub": uid1_str, "role": "authenticated"})
        async with factory() as session:
            conn = await session.connection()
            await conn.execute(text("SET role authenticated"))
            await conn.execute(
                text("SELECT set_config('request.jwt.claims', :c, false)").bindparams(c=claims)
            )
            result = await session.execute(select(Profile))
            profiles = list(result.scalars().all())

        assert len(profiles) == 1, f"RLS devrait limiter à 1 profil (user1), got {len(profiles)}"
        assert profiles[0].auth_user_id == uid1
    finally:
        delete_user(uid1_str)
        delete_user(uid2_str)
        await engine.dispose()
