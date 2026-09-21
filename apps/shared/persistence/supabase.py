"""Supabase SDK clients — user client on the publishable key, admin client on the secret key.

The admin client bypasses RLS: keep it inside the app boundary, never expose it to a browser.
"""

from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.settings.env import get_technical_settings
from supabase import AsyncClient, AsyncClientOptions, Client, acreate_client, create_client


async def get_user_supabase(client_ip: str | None = None) -> AsyncClient:
    """A GoTrue client for one visitor's call. ``client_ip`` rides along as ``Sb-Forwarded-For``:
    every call leaves from this server, so without it GoTrue's per-IP limit sees one caller."""
    s = get_technical_settings()
    headers = {"Sb-Forwarded-For": client_ip} if client_ip else {}
    return await acreate_client(
        s.supabase_api_url, s.supabase_publishable_key, options=AsyncClientOptions(headers=headers)
    )


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
