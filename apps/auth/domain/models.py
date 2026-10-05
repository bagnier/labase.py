"""The sign-in surface's bodies and answers. Blank fields are allowed: each handler answers them
on its own form rather than with a 422."""

from typing import Any

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    email: str = ""
    password: str = ""
    next: str = ""


class TotpVerification(BaseModel):
    code: str = ""
    factor_id: str = ""
    challenge_id: str = ""
    next: str = ""


class PasskeyAssertion(BaseModel):
    challenge_id: str = ""
    credential: dict[str, Any] = {}
    next: str = ""


class ImpersonationTarget(BaseModel):
    email: str = ""


class EmailAddress(BaseModel):
    email: str = ""


class LinkConfirmation(BaseModel):
    token_hash: str = ""
    type: str = "signup"
    next: str = ""


class PasswordResetForm(BaseModel):
    token_hash: str = ""
    password: str = ""


# ── What the sign-in surface answers ────────────────────────────────────────────────────────


class SessionIssued(BaseModel):
    access_token: str
    token_type: str = Field(default="bearer")


class PasskeySession(SessionIssued):
    redirect: str


class MfaRequired(BaseModel):
    """Second factor pending: the challenge to answer on ``/auth/mfa``."""

    mfa_required: bool = True
    factor_id: str
    challenge_id: str
    redirect: str  # the code form, for a script that cannot render it


class Impersonation(BaseModel):
    impersonating: str | None


class AccountRow(BaseModel):
    id: str
    email: str
    created_at: str
    confirmed: bool
    disabled: bool
    is_admin: bool


class AccountList(BaseModel):
    accounts: list[AccountRow]
