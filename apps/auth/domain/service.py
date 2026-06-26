from dataclasses import dataclass
from typing import cast

import httpx
import structlog
from supabase_auth.types import EmailOtpType, VerifyTokenHashParams

from apps.auth.contract.user import AuthenticatedUser as AuthenticatedUser
from apps.shared.config import get_technical_settings
from apps.shared.persistence.supabase import get_user_supabase

log = structlog.get_logger("labase.auth.service")


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
    s = get_technical_settings()
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"{s.supabase_api_url}/auth/v1/logout",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "apikey": s.supabase_publishable_key,
                },
            )
    except Exception:
        log.exception("auth.signout_failed")


async def refresh_session(refresh_token: str) -> AuthTokens:
    supabase = await get_user_supabase()
    auth = await supabase.auth.refresh_session(refresh_token)
    if auth.session is None:
        raise ValueError("Refresh failed")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


@dataclass
class RegisterResult:
    user_id: str
    access_token: str | None  # None when email confirmation is required


async def register(email: str, password: str) -> RegisterResult:
    """Signs up a new user. access_token is None when email confirmation is required."""
    supabase = await get_user_supabase()
    res = await supabase.auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise ValueError("Registration failed: no user returned")
    return RegisterResult(
        user_id=res.user.id,
        access_token=res.session.access_token if res.session else None,
    )


async def confirm_signup(token_hash: str, type: str = "signup") -> AuthTokens:
    """Exchange an email confirmation token for a session."""
    supabase = await get_user_supabase()
    res = await supabase.auth.verify_otp(
        VerifyTokenHashParams(token_hash=token_hash, type=cast(EmailOtpType, type))
    )
    if res.session is None:
        raise ValueError("Email confirmation failed: no session returned")
    return AuthTokens(
        access_token=res.session.access_token,
        refresh_token=res.session.refresh_token,
    )
