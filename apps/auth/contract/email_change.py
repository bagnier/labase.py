"""Email change, called by the profile form. GoTrue mails the new address;
``/auth/confirm-email`` finishes it. A trigger keeps ``profiles.email`` in sync.
"""

from apps.auth.contract.passwords import verify_password
from apps.auth.domain.service import EmailChangeError as EmailChangeError
from apps.auth.domain.service import request_email_change


async def change_email(
    email: str, current_password: str, new_email: str, session_access_token: str
) -> None:
    """Check the password, then have GoTrue mail the new address.

    The request uses the caller's session token: a fresh password login is AAL1, which GoTrue
    refuses for an account with MFA. Raises `WrongPassword` or `EmailChangeError`.
    """
    await verify_password(email, current_password)
    await request_email_change(session_access_token, new_email)
