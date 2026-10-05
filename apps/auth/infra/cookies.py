from fastapi import Response

from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import get_settings


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    max_age: int | None = None,
) -> None:
    """Hand a session over; the only place that does (AGENTS: signing in is one fact).

    The TTL is server-wide: one cookie serves every org. ``max_age`` shortens it to fit the
    impersonation window.
    """
    secure = get_technical_settings().cookies_secure
    if max_age is None:
        max_age = get_settings("users").session_ttl_seconds
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=max_age,
    )
