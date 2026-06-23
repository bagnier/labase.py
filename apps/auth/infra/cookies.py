from fastapi import Response

from apps.auth.contract import settings
from apps.shared.config import get_technical_settings


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = get_technical_settings().cookies_secure
    max_age = settings.session_ttl_seconds
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
