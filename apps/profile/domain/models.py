import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, UUIDPk, Versioned


class Profile(Base, UUIDPk, Versioned, Timestamped):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("user_id"),
        Index("profiles_email_idx", "email"),
        # Partial: the handle is set lazily on first profile access, so several rows may sit at
        # null at once — which a unique *constraint* would forbid.
        Index(
            "profiles_handle_idx",
            "handle",
            unique=True,
            postgresql_where=text("handle is not null"),
        ),
    )

    user_id: Mapped[uuid.UUID]
    email: Mapped[str] = mapped_column(String)
    handle: Mapped[str | None]
    avatar_path: Mapped[str | None]


class ProfileCreate(BaseModel):
    user_id: uuid.UUID
    email: str
    handle: str | None = None


class ProfileUpdate(BaseModel):
    handle: str | None = None


class HandleUpdate(BaseModel):
    """The profile form's one field; blank is refused by the handler on the form."""

    handle: str = ""


class PasswordChange(BaseModel):
    current_password: str = ""
    new_password: str = ""


class EmailChange(BaseModel):
    new_email: str = ""
    current_password: str = ""


class PasskeyRegistration(BaseModel):
    """The WebAuthn answer to a registration challenge, as the browser's script posts it."""

    challenge_id: str = ""
    credential: dict[str, Any] = {}


class TotpEnrolmentCheck(BaseModel):
    factor_id: str = ""
    code: str = ""


class AccountDeletion(BaseModel):
    """Re-authentication before the one irreversible action."""

    current_password: str = ""


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    handle: str | None
    avatar_path: str | None = None


# ── What the profile answers ───────────────────────────────────────────────────────────────


class ProfileStub(BaseModel):
    """An account with no profile row yet: only what the token says."""

    id: None = None
    handle: None = None
    email: str


class TotpEnrolmentRead(BaseModel):
    """What the authenticator app needs: the factor to confirm, its secret, the otpauth URI."""

    factor_id: str
    secret: str
    uri: str


class PasskeyRegistered(BaseModel):
    """A passkey now on the account, as GoTrue describes it."""

    message: str
    passkey: dict[str, Any]
