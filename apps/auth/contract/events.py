"""Auth's public events — a user's identity, sign-in, and account security on the shared trail.

Two lifecycle *signals* stay lean (subscribers react without importing one another):
:class:`UserCreated` and :class:`UserDeleted`. Everything else is a typed
:class:`~apps.shared.events.BusinessEvent`: sign-in outcomes, MFA/passkey, impersonation and the
self-service security actions a user takes from their profile (password, email, passkeys, 2FA) —
all ``auth.*`` — plus admin account gating (``accounts.*``). Failed/security-sensitive actions are
``warning``-level. The persister on the base records them; sign-in failures carry no actor.
"""

from dataclasses import dataclass
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.events import BusinessEvent


@dataclass(frozen=True)
class UserCreated:
    user_id: str
    email: str
    access_token: str | None


@dataclass(frozen=True)
class UserDeleted:
    """Emitted by the account-deletion flow, before the GoTrue soft delete.

    Carries the deleting request's (admin) session so handlers join its
    transaction — the deletion commits or rolls back as one unit.
    """

    user_id: str
    session: AsyncSession


class AuthEvent(BusinessEvent):
    entity: ClassVar[str] = "auth"
    icon: ClassVar[str] = "shield-check"


# ── Sign-in outcomes ─────────────────────────────────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class LoginFailed(AuthEvent):
    kind: ClassVar[str] = "auth.login_failed"
    level: ClassVar[str] = "warning"
    email: str | None = None


@dataclass(frozen=True, kw_only=True)
class RegisterFailed(AuthEvent):
    kind: ClassVar[str] = "auth.register_failed"
    level: ClassVar[str] = "warning"
    email: str | None = None


@dataclass(frozen=True, kw_only=True)
class MfaFailed(AuthEvent):
    kind: ClassVar[str] = "auth.mfa_failed"
    level: ClassVar[str] = "warning"
    factor_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class MfaVerified(AuthEvent):
    kind: ClassVar[str] = "auth.mfa_verified"
    factor_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class PasskeyFailed(AuthEvent):
    kind: ClassVar[str] = "auth.passkey_failed"
    level: ClassVar[str] = "warning"


@dataclass(frozen=True, kw_only=True)
class PasskeySignedIn(AuthEvent):
    kind: ClassVar[str] = "auth.passkey_signed_in"


@dataclass(frozen=True, kw_only=True)
class OAuthFailed(AuthEvent):
    kind: ClassVar[str] = "auth.oauth_failed"
    level: ClassVar[str] = "warning"


@dataclass(frozen=True, kw_only=True)
class OAuthSignedIn(AuthEvent):
    kind: ClassVar[str] = "auth.oauth_signed_in"


@dataclass(frozen=True, kw_only=True)
class ConfirmationResent(AuthEvent):
    kind: ClassVar[str] = "auth.confirmation_resent"
    email: str | None = None


@dataclass(frozen=True, kw_only=True)
class PasswordReset(AuthEvent):
    kind: ClassVar[str] = "auth.password_reset"


@dataclass(frozen=True, kw_only=True)
class SignedIn(AuthEvent):
    """A session issued via email+password — the password peer of ``OAuthSignedIn`` /
    ``PasskeySignedIn`` (a 2FA sign-in is marked by ``MfaVerified``). Closes the trail's blind
    spot where only *failed* sign-ins were recorded."""

    kind: ClassVar[str] = "auth.signed_in"


@dataclass(frozen=True, kw_only=True)
class SignedOut(AuthEvent):
    """A session was ended from the app — the lifecycle bookend of the sign-in events."""

    kind: ClassVar[str] = "auth.signed_out"


# ── Self-service account security (from the profile page) ────────────────────────


@dataclass(frozen=True, kw_only=True)
class PasswordChanged(AuthEvent):
    kind: ClassVar[str] = "auth.password_changed"


@dataclass(frozen=True, kw_only=True)
class EmailChangeRequested(AuthEvent):
    kind: ClassVar[str] = "auth.email_change_requested"
    new_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class EmailChanged(AuthEvent):
    kind: ClassVar[str] = "auth.email_changed"


@dataclass(frozen=True, kw_only=True)
class PasskeyAdded(AuthEvent):
    kind: ClassVar[str] = "auth.passkey_added"


@dataclass(frozen=True, kw_only=True)
class PasskeyRemoved(AuthEvent):
    kind: ClassVar[str] = "auth.passkey_removed"
    passkey_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class TwoFactorEnabled(AuthEvent):
    kind: ClassVar[str] = "auth.twofa_enabled"


# ── Admin: impersonation and denied admin access ─────────────────────────────────


@dataclass(frozen=True, kw_only=True)
class ImpersonationStarted(AuthEvent):
    kind: ClassVar[str] = "auth.impersonation_started"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class ImpersonationStopped(AuthEvent):
    kind: ClassVar[str] = "auth.impersonation_stopped"
    level: ClassVar[str] = "warning"
    target_email: str | None = None


@dataclass(frozen=True, kw_only=True)
class ForbiddenAdminAccess(AuthEvent):
    """A signed-in non-admin was denied an admin-only surface (answered 404, not 403). Recorded as
    a security signal — someone reaching for the console without rights — with the path tried."""

    kind: ClassVar[str] = "auth.forbidden_admin_access"
    level: ClassVar[str] = "warning"
    path: str | None = None


# ── Admin account gating (accounts.*) ────────────────────────────────────────────


class AccountsEvent(BusinessEvent):
    entity: ClassVar[str] = "accounts"
    icon: ClassVar[str] = "user-gear"


@dataclass(frozen=True, kw_only=True)
class AccountDisabled(AccountsEvent):
    kind: ClassVar[str] = "accounts.disabled"
    level: ClassVar[str] = "warning"
    target_user_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class AccountEnabled(AccountsEvent):
    kind: ClassVar[str] = "accounts.enabled"
    level: ClassVar[str] = "warning"
    target_user_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class AccountDeletedByAdmin(AccountsEvent):
    kind: ClassVar[str] = "accounts.deleted"
    level: ClassVar[str] = "warning"
    target_user_id: str | None = None
