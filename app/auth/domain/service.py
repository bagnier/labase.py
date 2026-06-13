from dataclasses import dataclass

import httpx
import structlog

from app.shared.config import get_settings
from app.shared.persistence.supabase import get_user_supabase

log = structlog.get_logger("labase.auth.service")


@dataclass
class AuthenticatedUser:
    id: str
    email: str
    access_token: str = ""


@dataclass
class AuthTokens:
    access_token: str
    refresh_token: str


async def login(email: str, password: str) -> AuthTokens:
    supabase = await get_user_supabase()
    auth = await supabase.auth.sign_in_with_password({"email": email, "password": password})
    if auth.session is None:
        raise ValueError("No session returned")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


async def logout(access_token: str) -> None:
    s = get_settings()
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{s.supabase_url}/auth/v1/logout",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "apikey": s.supabase_anon_key,
                },
            )
    except Exception:
        log.warning("auth.signout_failed")


async def refresh_session(refresh_token: str) -> AuthTokens:
    supabase = await get_user_supabase()
    auth = await supabase.auth.refresh_session(refresh_token)
    if auth.session is None:
        raise ValueError("Refresh failed")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


async def register(email: str, password: str) -> str:
    """Returns the new user's UUID (auth.users.id)."""
    supabase = await get_user_supabase()
    res = await supabase.auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise ValueError("Registration failed: no user returned")
    return res.user.id
