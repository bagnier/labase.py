from functools import lru_cache

from supabase import Client, create_client

from app.shared.config import get_settings


@lru_cache
def get_supabase() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_anon_key)


@lru_cache
def get_supabase_admin() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)
