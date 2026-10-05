"""Auth's events: accounts, sessions, impersonation and self-service security (``auth.*``), and
admin account gating (``accounts.*``). A refused sign-in or a wrong TOTP code changed nothing, so
it is a log line, not a fact.
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from apps.shared.events import BusinessEvent
from apps.shared.vocabulary import AppName, PhosphorIcon

# How the caller proved who they were; closed, so the journal stays groupable by method.
# ``email_link``: a mailed confirmation (signup, email change), whose token is the credential.
SignInMethod = Literal["password", "oauth", "passkey", "email_link"]


@dataclass(frozen=True, kw_only=True)
class UserCreated(BusinessEvent):
    """A new account; personal-org creation and the first-admin bootstrap react to it. Recorded
    once, by the signup trigger; the new user is the actor."""

    app_name: ClassVar[AppName] = "auth"  # not an AuthEvent: it has its own icon
    verb: ClassVar[str] = "user_created"
    icon: ClassVar[PhosphorIcon] = "user-plus"
    email: str


@dataclass(frozen=True, kw_only=True)
class UserDeleted(BusinessEvent):
    """An account was removed; membership and profile cleanup react to it, on the admin session
    since the user is gone. ``entity_id`` is the removed user, ``user_id`` whoever removed it."""

    app_name: ClassVar[AppName] = "auth"
    verb: ClassVar[str] = "user_deleted"
    icon: ClassVar[PhosphorIcon] = "user-minus"


class AuthEvent(BusinessEvent):
    app_name: ClassVar[AppName] = "auth"
    icon: ClassVar[PhosphorIcon] = "shield-check"


# ── Sign-in outcomes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ConfirmationResent(AuthEvent):
    verb: ClassVar[str] = "confirmation_resent"
    # the target address is entity_name


@dataclass(frozen=True, kw_only=True)
class PasswordReset(AuthEvent):
    verb: ClassVar[str] = "password_reset"


@dataclass(frozen=True, kw_only=True)
class SignedIn(AuthEvent):
    """A session was delivered (AGENTS: signing in is one fact). ``method`` and ``two_factor``
    describe it, so "who signed in, when" is one query."""

    verb: ClassVar[str] = "signed_in"
    method: SignInMethod
    two_factor: bool = False


@dataclass(frozen=True, kw_only=True)
class SignedOut(AuthEvent):
    """A session was ended from the app."""

    verb: ClassVar[str] = "signed_out"


# ── Self-service account security (from the profile page) ────────────────────────


@dataclass(frozen=True, kw_only=True)
class PasswordChanged(AuthEvent):
    verb: ClassVar[str] = "password_changed"


@dataclass(frozen=True, kw_only=True)
class EmailChangeRequested(AuthEvent):
    verb: ClassVar[str] = "email_change_requested"
    new_email: str


@dataclass(frozen=True, kw_only=True)
class EmailChanged(AuthEvent):
    verb: ClassVar[str] = "email_changed"


@dataclass(frozen=True, kw_only=True)
class PasskeyAdded(AuthEvent):
    verb: ClassVar[str] = "passkey_added"


@dataclass(frozen=True, kw_only=True)
class PasskeyRemoved(AuthEvent):
    verb: ClassVar[str] = "passkey_removed"
    # entity_id: the removed passkey


@dataclass(frozen=True, kw_only=True)
class TwoFactorEnabled(AuthEvent):
    verb: ClassVar[str] = "twofa_enabled"


# ── Admin: impersonation ─────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ImpersonationStarted(AuthEvent):
    verb: ClassVar[str] = "impersonation_started"
    # entity_id, entity_name: the impersonated user and their email


@dataclass(frozen=True, kw_only=True)
class ImpersonationStopped(AuthEvent):
    verb: ClassVar[str] = "impersonation_stopped"
    # entity_id, entity_name: the impersonated user and their email


# ── Admin account gating (accounts.*) ────────────────────────────────────────────


class AccountsEvent(BusinessEvent):
    app_name: ClassVar[AppName] = "accounts"
    icon: ClassVar[PhosphorIcon] = "user-gear"


@dataclass(frozen=True, kw_only=True)
class AccountDisabled(AccountsEvent):
    verb: ClassVar[str] = "disabled"


@dataclass(frozen=True, kw_only=True)
class AccountEnabled(AccountsEvent):
    verb: ClassVar[str] = "enabled"


@dataclass(frozen=True, kw_only=True)
class AccountDeletedByAdmin(AccountsEvent):
    verb: ClassVar[str] = "deleted"
