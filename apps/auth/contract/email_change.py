"""Email change — the auth surface the profile form calls.

GoTrue owns the flow (like forgot/reset password): the request mails a
confirmation to the NEW address, ``/auth/confirm-email`` finalizes it with
``verify_otp(type="email_change")``. A SQL trigger keeps ``profiles.email``
in sync whatever the change path.
"""

from supabase_auth.errors import AuthApiError

from apps.auth.contract.passwords import WrongPassword
from apps.auth.domain.service import EmailChangeError as EmailChangeError
from apps.auth.domain.service import login, request_email_change


async def change_email(email: str, current_password: str, new_email: str) -> None:
    """Re-authenticate, then ask GoTrue to send the confirmation to the new address.

    Raises `WrongPassword` when the current password is wrong and
    `EmailChangeError` (user-safe message) when GoTrue refuses the address.
    """
    try:
        tokens = await login(email, current_password)
    except AuthApiError as exc:
        raise WrongPassword from exc
    await request_email_change(tokens.access_token, new_email)
