"""Auth's public events — a user's identity, sessions and account security on the shared journal.

One lifecycle *signal* stays lean (subscribers react without importing one another):
:class:`UserDeleted`. Everything else is a typed :class:`~apps.shared.events.BusinessEvent`:
account creation, signing in and out, impersonation, and the self-service security actions a user
takes from their profile (password, email, passkeys, 2FA) — all ``auth.*`` — plus admin account
gating (``accounts.*``).

What is **not** here is as deliberate: a refused sign-in, a wrong TOTP code, a denied admin surface.
Nothing happened in those, so they are structured log lines (``labase.auth.*``), read from the
console's Logs screen alongside the journal. Only a delivered session is a fact, and one kind
carries it whatever the ceremony — see :class:`SignedIn`.
"""

from dataclasses import dataclass
from typing import ClassVar, Literal

from apps.shared.events import BusinessEvent

# How a caller proved who they were. A closed set on purpose: the type checker rejects a fifth
# spelling of "password" before a row can carry it, which is what keeps the journal groupable by
# method years later. ``email_link`` covers both mailed confirmations (signup, email change), whose
# single-use token *is* the credential.
SignInMethod = Literal["password", "oauth", "passkey", "email_link"]


@dataclass(frozen=True, kw_only=True)
class UserCreated(BusinessEvent):
    """A new account was provisioned — the fact org seeding and first-admin bootstrap react to.

    Distinct from a sign-in (the ``*SignedIn`` Login events): emitted once, at genuine account
    creation — never on a returning OAuth login — so the journal records real signups only. The new
    user is the actor; a token is never carried (and would be redacted from any payload anyway)."""

    app_name: ClassVar[str] = "auth"  # outside AuthEvent (own icon), so it names its app here
    verb: ClassVar[str] = "user_created"
    icon: ClassVar[str] = "user-plus"
    email: str  # the new account's email — always present at genuine creation


@dataclass(frozen=True, kw_only=True)
class UserDeleted(BusinessEvent):
    """An account was removed — the fact membership/profile cleanup reacts to.

    Distinct from the audit events (:class:`AccountDeleted` / :class:`AccountDeletedByAdmin`): this
    is the lifecycle trigger the forget consumers key on. The removed user is ``entity_id``;
    ``user_id`` is whoever triggered it (the user themselves, or an admin). No live session — the
    user is gone, so cleanup runs asynchronously on the admin session, by user id (RLS-as-user is
    impossible)."""

    app_name: ClassVar[str] = "auth"
    verb: ClassVar[str] = "user_deleted"
    icon: ClassVar[str] = "user-minus"


class AuthEvent(BusinessEvent):
    app_name: ClassVar[str] = "auth"
    icon: ClassVar[str] = "shield-check"


# ── Sign-in outcomes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ConfirmationResent(AuthEvent):
    verb: ClassVar[str] = "confirmation_resent"
    # the target account rides in entity_name


@dataclass(frozen=True, kw_only=True)
class PasswordReset(AuthEvent):
    verb: ClassVar[str] = "password_reset"


@dataclass(frozen=True, kw_only=True)
class SignedIn(AuthEvent):
    """A session was delivered to someone — the one fact of signing in, whatever obtained it.

    ``method`` is how the caller proved who they were and ``two_factor`` whether a second factor was
    cleared on the way: both are *properties of this session*, not separate facts. Keeping them in
    the payload rather than in the ``kind`` is what makes "who signed in, and when" a single query —
    the previous vocabulary split it across four kinds, and still left two paths recording nothing.

    Emitted at the moment the session is handed over (``set_auth_cookies``), never before: a sign-in
    that a second factor then refuses never happened.
    """

    verb: ClassVar[str] = "signed_in"
    method: SignInMethod
    two_factor: bool = False


@dataclass(frozen=True, kw_only=True)
class SignedOut(AuthEvent):
    """A session was ended from the app — the lifecycle bookend of the sign-in events."""

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
    # the removed passkey is the subject: its id rides on entity_id


@dataclass(frozen=True, kw_only=True)
class TwoFactorEnabled(AuthEvent):
    verb: ClassVar[str] = "twofa_enabled"


# ── Admin: impersonation and denied admin access ─────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ImpersonationStarted(AuthEvent):
    verb: ClassVar[str] = "impersonation_started"
    # the impersonated user: entity_id resolved from the email, entity_name = the email


@dataclass(frozen=True, kw_only=True)
class ImpersonationStopped(AuthEvent):
    verb: ClassVar[str] = "impersonation_stopped"
    # the impersonated user: entity_id = their id, entity_name = the email


# ── Admin account gating (accounts.*) ────────────────────────────────────────────


class AccountsEvent(BusinessEvent):
    app_name: ClassVar[str] = "accounts"
    icon: ClassVar[str] = "user-gear"


@dataclass(frozen=True, kw_only=True)
class AccountDisabled(AccountsEvent):
    verb: ClassVar[str] = "disabled"


@dataclass(frozen=True, kw_only=True)
class AccountEnabled(AccountsEvent):
    verb: ClassVar[str] = "enabled"


@dataclass(frozen=True, kw_only=True)
class AccountDeletedByAdmin(AccountsEvent):
    verb: ClassVar[str] = "deleted"
