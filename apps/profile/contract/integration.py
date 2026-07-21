"""How the profile context plugs into the running app: mounts its router, claims its slug."""

import uuid

from sqlalchemy import func, select

from apps.auth.contract.events import UserDeleted
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.profile.contract.fullpage import provide_profile_handle
from apps.profile.contract.queries import profile_handle_taken
from apps.profile.domain.models import Profile
from apps.profile.infra.router import router
from apps.shared.host import Host, MountPhase
from apps.shared.persistence.repository import count_created_per_day
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink

PHASE = MountPhase.FOUNDATION

_GROWTH_DAYS = 14


def mount(host: Host) -> None:
    host.app.include_router(router, tags=["profile"])
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("profile", provide_profile_handle)
    # Advanced-auth options are individually admin-switchable (2026-07-06 decision).
    host.register_settings(_declare_settings())
    host.events.on(UserDeleted, _forget_user)
    host.reserve("profile")
    host.register_open_list("profiles", profile_handle_taken)


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
    # A profile exists 1:1 per account, so the raw total just echoes the Users tile.
    # Lead with what's profile-specific instead: handle adoption (public identity).
    if count:
        lines = [f"{handles} with a handle", f"{count - handles} without"]
    else:
        lines = ["No profiles yet"]
    return ConsoleOverview(
        key="profile",
        title="Profiles",
        icon="user-circle",
        section="identity",
        data={
            "lines": lines,
            # Sign-ups per day (every account gets a profile row on creation) — the
            # console landing folds every tile's "growth" slice into one chart. The
            # series reads "Sign-ups", not the tile title, via "growth_label".
            "growth": await count_created_per_day(query.session, Profile, days=_GROWTH_DAYS),
            "growth_label": "Sign-ups",
        },
    )
