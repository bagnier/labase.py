from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.config import get_settings
from supabase import AsyncClient, Client, acreate_client, create_client


async def get_user_supabase() -> AsyncClient:
    s = get_settings()
    return await acreate_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def get_admin_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


async def auth_user_exists(admin_session: AsyncSession, email: str) -> bool:
    result = await admin_session.execute(
        text("SELECT 1 FROM auth.users WHERE lower(email) = lower(:email) LIMIT 1"),
        {"email": email},
    )
    return result.first() is not None
