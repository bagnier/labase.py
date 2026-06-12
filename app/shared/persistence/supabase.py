from functools import lru_cache

from app.shared.config import get_settings
from supabase import AsyncClient, Client, acreate_client, create_client


async def make_auth_client() -> AsyncClient:
    s = get_settings()
    return await acreate_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def get_supabase_admin() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)
