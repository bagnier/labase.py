"""Password management — the auth surface other contexts may call (profile's form)."""

from supabase_auth.errors import AuthApiError

from apps.auth.domain.service import PasswordUpdateError as PasswordUpdateError
from apps.auth.domain.service import login, update_password


class WrongPassword(Exception):
    """The provided current password did not authenticate."""


async def verify_password(email: str, current_password: str) -> None:
    """Re-authenticate before a sensitive action (deletion…); raises `WrongPassword`."""
    try:
        await login(email, current_password)
    except AuthApiError as exc:
        raise WrongPassword from exc


async def change_password(
    email: str, current_password: str, new_password: str, session_access_token: str
) -> None:
    """Re-authenticate with the current password, then set the new one.

    The update itself runs on the caller's own session token — a fresh
    password-only login is AAL1 and GoTrue rejects the update when the
    account has MFA enabled, requiring the session's already-verified AAL2.

    Raises `WrongPassword` when the current password is wrong and
    `PasswordUpdateError` (user-safe message) when GoTrue refuses the new one.
    """
    try:
        await login(email, current_password)
    except AuthApiError as exc:
        raise WrongPassword from exc
    await update_password(session_access_token, new_password)
