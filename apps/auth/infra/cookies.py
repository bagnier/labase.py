from fastapi import Response

from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import get_settings


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
    max_age: int | None = None,
) -> None:
    """Hand a session over to the caller — the single place that does.

    The TTL is server-wide auth policy, deliberately not org-overridable: the cookie is user-global,
    one session across every org, set at login outside any ``/{org_handle}``. A caller may pass a
    shorter ``max_age`` to keep a re-emitted session inside a time-boxed window (impersonation),
    where the default long TTL would defeat the box.
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
