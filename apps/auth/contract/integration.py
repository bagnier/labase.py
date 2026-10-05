"""Auth's mount: routers, events, settings, console tile and slugs."""

from apps.auth.contract.events import (
    AccountDeletedByAdmin,
    AccountDisabled,
    AccountEnabled,
    ConfirmationResent,
    EmailChanged,
    EmailChangeRequested,
    ImpersonationStarted,
    ImpersonationStopped,
    PasskeyAdded,
    PasskeyRemoved,
    PasswordChanged,
    PasswordReset,
    SignedIn,
    SignedOut,
    TwoFactorEnabled,
    UserCreated,
    UserDeleted,
)
from apps.auth.infra.accounts_router import accounts_router
from apps.auth.infra.router import router
from apps.auth.infra.user_repository import list_server_admins
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.shared.integration.host import Host, MountPhase
from apps.shared.settings.live import ConsoleLink, SettingDef, SettingsDeclaration, SupabaseLink

PHASE = MountPhase.FOUNDATION


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/auth", tags=["auth"])
    # Before the console context mounts: /console/accounts must precede /console/{app}.
    host.app.include_router(accounts_router, prefix="/console/accounts")
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    host.register_settings(_declare_settings())
    host.reserve("auth", "login", "logout", "signup")
    # ``auth.*`` and ``accounts.*``: each event names its own app.
    host.events.declare(
        UserCreated,
        UserDeleted,
        SignedIn,
        SignedOut,
        ConfirmationResent,
        PasswordReset,
        PasswordChanged,
        EmailChangeRequested,
        EmailChanged,
        TwoFactorEnabled,
        PasskeyAdded,
        PasskeyRemoved,
        ImpersonationStarted,
        ImpersonationStopped,
        AccountDisabled,
        AccountEnabled,
        AccountDeletedByAdmin,
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="users",
        defs=[
            SettingDef(
                "session_ttl_seconds",
                "number",
                "604800",
                "Session cookie lifetime, in seconds",
            ),
            SettingDef(
                "resend_confirmation_enabled",
                "boolean",
                "true",
                "Offer to resend the confirmation email on blocked sign-ins",
            ),
            SettingDef(
                "user_management_enabled",
                "boolean",
                "true",
                "Console screen to disable or delete server accounts",
            ),
            SettingDef(
                "two_factor_enabled",
                "boolean",
                "true",
                "Authenticator-app (TOTP) two-factor sign-in",
            ),
            SettingDef(
                "passkeys_enabled",
                "boolean",
                "false",
                "Passkey (WebAuthn) sign-in — also needs [auth.passkey] in supabase/config.toml",
            ),
            SettingDef(
                "oauth_google_enabled",
                "boolean",
                "false",
                "Sign in with Google (needs provider credentials in Supabase — see docs/oauth.md)",
            ),
            SettingDef(
                "oauth_github_enabled",
                "boolean",
                "false",
                "Sign in with GitHub (needs provider credentials in Supabase — see docs/oauth.md)",
            ),
        ],
        supabase=SupabaseLink("Manage users in Supabase Auth", "auth/users"),
        links=(
            ConsoleLink("Accounts", "/console/accounts"),
            ConsoleLink("Manage admins", "/console/admins"),
        ),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    # Accounts live in GoTrue: counted through the admin API.
    count = len(await list_server_admins())
    lines = [f"{count} user" + ("s" if count > 1 else "")] if count else ["No users yet"]
    return ConsoleOverview(
        key="users", title="Users", icon="users", section="identity", data={"lines": lines}
    )
