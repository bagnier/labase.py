"""Auth's public events — a user's identity, sign-in, and account security on the shared trail.

One lifecycle *signal* stays lean (subscribers react without importing one another):
:class:`UserDeleted`. Everything else is a typed :class:`~apps.shared.events.BusinessEvent`:
account creation, sign-in outcomes, MFA/passkey, impersonation and the self-service security
actions a user takes from their profile (password, email, passkeys, 2FA) — all ``auth.*`` — plus
admin account gating (``accounts.*``). Failed/security-sensitive actions are ``warning``-level.
The persister on the base records them; sign-in failures carry no actor.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent


@dataclass(frozen=True, kw_only=True)
class UserCreated(BusinessEvent):
    """A new account was provisioned — the fact org seeding and first-admin bootstrap react to.

    Distinct from a sign-in (the ``*SignedIn`` Login events): emitted once, at genuine account
    creation — never on a returning OAuth login — so the trail records real signups only. The new
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
class LoginFailed(AuthEvent):
    verb: ClassVar[str] = "login_failed"
    # the attempted account rides in entity_name — no account is guaranteed to exist


@dataclass(frozen=True, kw_only=True)
class RegisterFailed(AuthEvent):
    verb: ClassVar[str] = "register_failed"
    # the attempted account rides in entity_name


@dataclass(frozen=True, kw_only=True)
class MfaFailed(AuthEvent):
    """A TOTP challenge was answered wrong. The subject is the account that failed it — resolved
    from the half-issued MFA token, which is more than the factor id ever said."""

    verb: ClassVar[str] = "mfa_failed"


@dataclass(frozen=True, kw_only=True)
class MfaVerified(AuthEvent):
    verb: ClassVar[str] = "mfa_verified"


@dataclass(frozen=True, kw_only=True)
class PasskeyFailed(AuthEvent):
    verb: ClassVar[str] = "passkey_failed"


@dataclass(frozen=True, kw_only=True)
class PasskeySignedIn(AuthEvent):
    verb: ClassVar[str] = "passkey_signed_in"


@dataclass(frozen=True, kw_only=True)
class OAuthFailed(AuthEvent):
    verb: ClassVar[str] = "oauth_failed"


@dataclass(frozen=True, kw_only=True)
class OAuthSignedIn(AuthEvent):
    verb: ClassVar[str] = "oauth_signed_in"


@dataclass(frozen=True, kw_only=True)
class ConfirmationResent(AuthEvent):
    verb: ClassVar[str] = "confirmation_resent"
    # the target account rides in entity_name


@dataclass(frozen=True, kw_only=True)
class PasswordReset(AuthEvent):
    verb: ClassVar[str] = "password_reset"


@dataclass(frozen=True, kw_only=True)
class SignedIn(AuthEvent):
    """A session issued via email+password — the password peer of ``OAuthSignedIn`` /
    ``PasskeySignedIn`` (a 2FA sign-in is marked by ``MfaVerified``). Closes the trail's blind
    spot where only *failed* sign-ins were recorded."""

    verb: ClassVar[str] = "signed_in"


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


@dataclass(frozen=True, kw_only=True)
class ForbiddenAdminAccess(AuthEvent):
    """A signed-in non-admin was denied an admin-only surface (answered 404, not 403). Recorded as
    a security signal — someone reaching for the console without rights — with the path tried."""

    verb: ClassVar[str] = "forbidden_admin_access"
    path: str


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
