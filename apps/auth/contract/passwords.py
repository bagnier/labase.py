"""Password checks and changes, for other contexts (the profile)."""

from supabase_auth.errors import AuthApiError

from apps.auth.domain.service import PasswordUpdateError as PasswordUpdateError
from apps.auth.domain.service import login, update_password


class WrongPassword(Exception):
    """The provided current password did not authenticate."""


async def verify_password(email: str, current_password: str) -> None:
    """Before a sensitive action (deletion); raises `WrongPassword`."""
    try:
        await login(email, current_password)
    except AuthApiError as exc:
        raise WrongPassword from exc


async def change_password(
    email: str, current_password: str, new_password: str, session_access_token: str
) -> None:
    """Check the current password, then set the new one.

    The update uses the caller's session token: a fresh password login is AAL1, which GoTrue
    refuses for an account with MFA. Raises `WrongPassword` or `PasswordUpdateError`.
    """
    await verify_password(email, current_password)
    await update_password(session_access_token, new_password)
