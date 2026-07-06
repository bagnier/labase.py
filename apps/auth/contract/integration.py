"""How the auth context plugs into the running app: mounts the auth router, claims its slugs.

Event wiring for sign-up (``UserCreated`` emission, compensation) lives in the registration
orchestrator (:mod:`app.registration`), not here.
"""

from apps.auth.contract import settings
from apps.auth.contract.admin import list_server_admins
from apps.auth.infra.router import router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
)
from apps.shared.host import Host


def mount(host: Host) -> None:
    host.app.include_router(router, prefix="/auth", tags=["auth"])
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
        ],
        supabase=SupabaseLink("Manage users in Supabase Auth", "auth/users"),
    )
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.reserve("auth", "login", "logout", "signup")


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    # Accounts live in Supabase GoTrue, not a table — count via the admin API.
    count = len(await list_server_admins())
    lines = [f"{count} user" + ("s" if count > 1 else "")] if count else ["No users yet"]
    return ConsoleOverview(key="users", title="Users", icon="users", data={"lines": lines})
