"""How the auth context plugs into the running app: mounts the auth router, claims its slugs.

Event wiring for sign-up (``UserCreated`` emission, compensation) lives in the registration
orchestrator (:mod:`app.registration`), not here.
"""

from apps.auth.contract import settings
from apps.auth.contract.admin import list_server_admins
from apps.auth.infra.accounts_router import accounts_router
from apps.auth.infra.router import router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    ConsoleLink,
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
)
from apps.shared.host import Host


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/auth", tags=["auth"])
    # Before the settings context mounts: /console/accounts must precede /console/{app}.
    host.app.include_router(accounts_router, prefix="/console/accounts")
    host.events.on(ConsoleOverviewQuery, _console_overview)
    settings.group = declare_app_settings(
        "users",
        defs=[
            SettingDef(
                "session_ttl_seconds", "number", "604800", "Session cookie lifetime, in seconds"
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
        links=(ConsoleLink("Accounts", "/console/accounts"),),
    )
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.reserve("auth", "login", "logout", "signup")


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    # Accounts live in Supabase GoTrue, not a table — count via the admin API.
    count = len(await list_server_admins())
    lines = [f"{count} user" + ("s" if count > 1 else "")] if count else ["No users yet"]
    return ConsoleOverview(key="users", title="Users", icon="users", data={"lines": lines})
