"""Supabase SDK clients — user client on the publishable key, admin client on the secret key.

The admin client bypasses RLS: keep it inside the app boundary, never expose it to a browser.
"""

from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.config import get_technical_settings
from supabase import AsyncClient, Client, acreate_client, create_client


async def get_user_supabase() -> AsyncClient:
    s = get_technical_settings()
    return await acreate_client(s.supabase_api_url, s.supabase_publishable_key)


@lru_cache
def get_admin_supabase() -> Client:
    s = get_technical_settings()
    return create_client(s.supabase_api_url, s.supabase_secret_key)


async def auth_user_exists(admin_session: AsyncSession, email: str) -> bool:
    result = await admin_session.execute(
        text("SELECT 1 FROM auth.users WHERE lower(email) = lower(:email) LIMIT 1"),
        {"email": email},
    )
    return result.first() is not None
