from dataclasses import dataclass

import structlog

from app.shared.persistence.supabase import get_supabase

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


def login(email: str, password: str) -> AuthTokens:
    auth = get_supabase().auth.sign_in_with_password({"email": email, "password": password})
    if auth.session is None:
        raise ValueError("No session returned")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


def logout() -> None:
    try:
        get_supabase().auth.sign_out()
    except Exception:
        log.warning("auth.signout_failed")


def refresh_session(refresh_token: str) -> AuthTokens:
    auth = get_supabase().auth.refresh_session(refresh_token)
    if auth.session is None:
        raise ValueError("Refresh failed")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


def register(email: str, password: str) -> str:
    """Returns the new user's UUID (auth.users.id)."""
    res = get_supabase().auth.sign_up({"email": email, "password": password})
    if res.user is None:
        raise ValueError("Registration failed: no user returned")
    return res.user.id
