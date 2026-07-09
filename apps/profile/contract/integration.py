"""How the profile context plugs into the running app: mounts its router, claims its slug."""

import uuid

from sqlalchemy import func, select

from apps.auth.contract.events import UserDeleted
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.profile.contract.fullpage import provide_profile_handle
from apps.profile.contract.queries import profile_handle_taken
from apps.profile.domain.models import Profile
from apps.profile.infra.router import router
from apps.shared.host import Host
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink
from apps.shared.slug_registry import register_open_list


def mount(host: Host) -> None:
    host.app.include_router(router, tags=["profile"])
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("profile", provide_profile_handle)
    # Advanced-auth options are individually admin-switchable (2026-07-06 decision).
    host.register_settings(_declare_settings())
    host.events.on(UserDeleted, _forget_user)
    host.reserve("profile")
    register_open_list("profiles", profile_handle_taken)


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="profile",
        defs=[
            SettingDef(
                "email_change_enabled",
                "boolean",
                "true",
                "Allow users to change their sign-in email",
            ),
            SettingDef(
                "account_deletion_enabled",
                "boolean",
                "true",
                "Allow users to delete their own account",
            ),
            SettingDef(
                "avatar_enabled",
                "boolean",
                "true",
                "Allow users to upload a profile photo",
            ),
            SettingDef(
                "handle_enabled",
                "boolean",
                "true",
                "Public @handles on profiles",
            ),
        ],
        supabase=SupabaseLink("Browse profiles in Supabase", table="profiles"),
    )


async def _forget_user(event: UserDeleted) -> None:
    """Account deletion: drop the profile row, in the deleting request's transaction."""
    profile = await event.session.scalar(
        select(Profile).where(Profile.auth_user_id == uuid.UUID(event.user_id))
    )
    if profile is not None:
        await event.session.delete(profile)
        await event.session.flush()


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
        key="profile",
        title="Profiles",
        icon="user-circle",
        section="configuration",
        data={"lines": lines},
    )
