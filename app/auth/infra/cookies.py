from fastapi import Response

from app.shared.config import get_settings

_COOKIE_MAX_AGE = 60 * 60 * 24 * 7


def set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    secure = not get_settings().debug
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=_COOKIE_MAX_AGE,
    )
