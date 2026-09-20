"""The bodies the sign-in surface takes — one Pydantic model per form, so the schema says what
each mutation reads and a JSON caller can send it. Blanks stay blanks: each handler answers an
empty field with its own message on its own form, not with a 422."""

from typing import Any

from pydantic import BaseModel, Field


class Credentials(BaseModel):
    """Sign-in and registration alike: an address, a password, and where to go next."""

    email: str = ""
    password: str = ""
    next: str = ""


class TotpVerification(BaseModel):
    code: str = ""
    factor_id: str = ""
    challenge_id: str = ""
    next: str = ""


class PasskeyAssertion(BaseModel):
    """The WebAuthn answer to a sign-in challenge, as the browser's script posts it."""

    challenge_id: str = ""
    credential: dict[str, Any] = {}
    next: str = ""


class ImpersonationTarget(BaseModel):
    email: str = ""


class EmailAddress(BaseModel):
    """A mailed flow's only input — the reset request, the confirmation resend."""

    email: str = ""


class PasswordResetForm(BaseModel):
    """The mailed recovery token and the password to set with it."""

    token_hash: str = ""
    password: str = ""


# ── What the sign-in surface answers ────────────────────────────────────────────────────────


class SessionIssued(BaseModel):
    """A session handed over: the bearer token a JSON caller uses from here on."""

    access_token: str
    token_type: str = Field(default="bearer")


class PasskeySession(SessionIssued):
    """The same, with where the page's script should send the browser."""

    redirect: str


class MfaRequired(BaseModel):
    """Correct password, second factor pending: the challenge to answer on ``/auth/mfa``."""

    mfa_required: bool = True
    factor_id: str
    challenge_id: str


class Impersonation(BaseModel):
    """Who the admin is acting as — ``None`` once they stopped."""

    impersonating: str | None


class AccountRow(BaseModel):
    """One GoTrue account as the console lists it."""

    id: str
    email: str
    created_at: str
    confirmed: bool
    disabled: bool
    is_admin: bool


class AccountList(BaseModel):
    accounts: list[AccountRow]
