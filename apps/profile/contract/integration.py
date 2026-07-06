"""How the profile context plugs into the running app: mounts its router, claims its slug."""

from sqlalchemy import func, select

from apps.profile.contract import settings
from apps.profile.contract.fullpage import provide_profile_handle
from apps.profile.contract.queries import profile_handle_taken
from apps.profile.domain.models import Profile
from apps.profile.infra.router import router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
)
from apps.shared.host import Host
from apps.shared.slug_registry import register_open_list


def mount(host: Host) -> None:
    host.app.include_router(router, tags=["profile"])
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("profile", provide_profile_handle)
    # Advanced-auth options are individually admin-switchable (2026-07-06 decision).
    settings.group = declare_app_settings(
        "profile",
        defs=[
            SettingDef(
                "email_change_enabled",
                "boolean",
                "true",
                "Allow users to change their sign-in email",
            ),
        ],
        supabase=SupabaseLink("Browse profiles in Supabase", table="profiles"),
    )
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.reserve("profile")
    register_open_list("profiles", profile_handle_taken)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    count = await query.session.scalar(select(func.count()).select_from(Profile)) or 0
    handles = (
        await query.session.scalar(
            select(func.count()).select_from(Profile).where(Profile.handle.isnot(None))
        )
        or 0
    )
    if count:
        lines = [f"{count} profile" + ("s" if count > 1 else ""), f"{handles} with a handle"]
    else:
        lines = ["No profiles yet"]
    return ConsoleOverview(
        key="profile", title="Profiles", icon="user-circle", data={"lines": lines}
    )
