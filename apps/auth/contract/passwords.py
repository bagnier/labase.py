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


async def change_password(email: str, current_password: str, new_password: str) -> None:
    """Re-authenticate with the current password, then set the new one.

    Raises `WrongPassword` when the current password is wrong and
    `PasswordUpdateError` (user-safe message) when GoTrue refuses the new one.
    """
    try:
        tokens = await login(email, current_password)
    except AuthApiError as exc:
        raise WrongPassword from exc
    await update_password(tokens.access_token, new_password)
