"""Email change — the auth surface the profile form calls.

GoTrue owns the flow (like forgot/reset password): the request mails a
confirmation to the NEW address, ``/auth/confirm-email`` finalizes it with
``verify_otp(type="email_change")``. A SQL trigger keeps ``profiles.email``
in sync whatever the change path.
"""

from apps.auth.contract.passwords import verify_password
from apps.auth.domain.service import EmailChangeError as EmailChangeError
from apps.auth.domain.service import request_email_change


async def change_email(
    email: str, current_password: str, new_email: str, session_access_token: str
) -> None:
    """Re-authenticate, then ask GoTrue to send the confirmation to the new address.

    The request itself runs on the caller's own session token — a fresh
    password-only login is AAL1 and GoTrue rejects the update when the
    account has MFA enabled, requiring the session's already-verified AAL2.

    Raises `WrongPassword` when the current password is wrong and
    `EmailChangeError` (user-safe message) when GoTrue refuses the address.
    """
    await verify_password(email, current_password)
    await request_email_change(session_access_token, new_email)
