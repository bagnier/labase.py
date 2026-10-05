"""The profile mount."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.events import UserDeleted
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.profile.contract.events import AccountDeleted, AvatarUpdated, HandleChanged
from apps.profile.contract.fullpage import provide_profile_handle
from apps.profile.contract.queries import profile_handle_taken
from apps.profile.domain.models import Profile
from apps.profile.infra.router import router
from apps.shared.integration.host import Host, MountPhase
from apps.shared.persistence.repository import count_created_per_day, count_where
from apps.shared.settings.live import SettingDef, SettingsDeclaration, SupabaseLink

PHASE = MountPhase.FOUNDATION

_GROWTH_DAYS = 14


def mount(host: Host) -> None:
    host.app.include_router(router, tags=["profile"])
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("profile", ["handle", "avatar_path"], provide_profile_handle)
    host.register_settings(_declare_settings())
    host.events.declare(AccountDeleted, AvatarUpdated, HandleChanged)
    host.events.on(UserDeleted, _forget_user, name="profile_forget", app="profile")
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


async def _forget_user(session: AsyncSession, event: UserDeleted) -> None:
    """Delete the deleted user's profile row."""
    entity_id = event.entity_id
    user_id = entity_id if isinstance(entity_id, uuid.UUID) else uuid.UUID(entity_id)
    profile = await session.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is not None:
        await session.delete(profile)
        await session.flush()


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    count = await count_where(query.session, Profile)
    handles = await count_where(query.session, Profile, Profile.handle.isnot(None))
    # One profile per account: the handle adoption says more than the total.
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
            # Profiles per day are sign-ups: labelled so on the console chart.
            "growth": await count_created_per_day(query.session, Profile, days=_GROWTH_DAYS),
            "growth_label": "Sign-ups",
        },
    )
