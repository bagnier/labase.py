"""The organizations mount, and the reactions creating a user's personal org and forgetting a
deleted user (AGENTS: sign-up is a chain of durable reactions).
"""

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.events import UserCreated, UserDeleted
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import (
    InvitationRevoked,
    InvitationSent,
    MemberJoined,
    MemberLeft,
    MemberRemoved,
    MemberRoleChanged,
    OrganizationCreated,
    OrganizationRenamed,
    OrgHandleChanged,
)
from apps.organizations.contract.fullpage import provide_org_nav
from apps.organizations.contract.queries import org_handle_taken, user_exists
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.invitation_router import router as invitation_router
from apps.organizations.infra.repository import OrganizationRepository
from apps.organizations.infra.router import org_router, router
from apps.shared.events.bus import events
from apps.shared.integration.host import Host, MountPhase, NavItem
from apps.shared.overview import pluralize
from apps.shared.persistence.repository import count_where
from apps.shared.settings.live import SettingDef, SettingsDeclaration, SupabaseLink, get_settings

PHASE = MountPhase.ORG

log = structlog.get_logger(__name__)


def mount(host: Host) -> None:
    # A core context: no on/off switch.
    host.register_settings(_declare_settings())
    host.app.include_router(invitation_router)
    host.app.include_router(router)
    host.app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.declare(
        OrganizationCreated,
        OrganizationRenamed,
        OrgHandleChanged,
        MemberJoined,
        MemberLeft,
        MemberRoleChanged,
        MemberRemoved,
        InvitationSent,
        InvitationRevoked,
    )
    host.events.on(UserCreated, _create_org, name="create_personal_org", app="organizations")
    host.events.on(UserDeleted, _forget_user, name="organizations_forget", app="organizations")
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("org", ["nav"], provide_org_nav)
    host.register_nav(
        NavItem("Settings", "gear", "settings", "/settings", order=110, owner_only=True)
    )
    host.reserve("organizations", "invitations")
    host.register_open_list("organizations", org_handle_taken)


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="organizations",
        defs=[
            SettingDef(
                "max_owned_orgs_per_user",
                "number",
                "-1",
                "Max organisations owned per user (-1 = unlimited)",
            ),
            SettingDef(
                "auto_create_personal_org",
                "boolean",
                "true",
                "Create a personal organisation on sign-up",
            ),
            SettingDef(
                "seed_welcome_content",
                "boolean",
                "true",
                "Seed welcome content in new organisations",
            ),
            SettingDef(
                "max_invitations_per_org",
                "number",
                "-1",
                "Max pending invitations per organisation (-1 = unlimited)",
            ),
        ],
        supabase=SupabaseLink("Browse organisations in Supabase", table="organizations"),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    orgs = await count_where(query.session, Organization)
    members = await count_where(query.session, Membership)
    if orgs:
        lines = [
            f"{orgs} {pluralize(orgs, 'organisation')}",
            f"{members} {pluralize(members, 'member')}",
        ]
    else:
        lines = ["No organisations yet"]
    return ConsoleOverview(
        key="organizations",
        title="Organisations",
        icon="buildings",
        section="identity",
        # No "growth": orgs per day would mirror sign-ups, one personal org each.
        data={"lines": lines},
    )


async def _create_org(session: AsyncSession, event: UserCreated) -> None:
    """Create the user's personal org and record ``OrganizationCreated``, committed together by
    the worker. Idempotent, for a retried delivery."""
    if not get_settings("organizations").auto_create_personal_org:
        return
    user_id = event.user_id
    if user_id is None:
        return
    # The user may have deleted their account since: a clean no-op.
    if not await user_exists(session, user_id):
        log.info("create_personal_org.actor_gone", user_id=str(user_id))
        return
    # A personal org: a team org created meanwhile must not count.
    already_owns_one = await OrganizationRepository(session).count_personal_owned_by(user_id)
    if already_owns_one:
        return
    try:
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            user_id=user_id,
            is_personal=True,
        )
    except IntegrityError:
        # Which constraint failed is unknown: if the user still exists, it was not their
        # deletion, and the worker retries then parks.
        await session.rollback()
        if await user_exists(session, user_id):
            raise
        log.info("create_personal_org.actor_gone", user_id=str(user_id))
        return
    await session.flush()  # assigns org.id
    await events.emit(
        OrganizationCreated(
            user_id=user_id,
            org_id=org.id,
            entity_id=org.id,
            entity_name=org.name,
        ),
        session=session,
    )


async def _forget_user(session: AsyncSession, event: UserDeleted) -> None:
    """Drop the deleted user's memberships, deleting any org left without owner or member.

    A last owner's org is deleted whole: the database refuses an ownerless org, and its cascade is
    exempt from that guard.
    """
    user_id = event.entity_id
    if user_id is None:
        return
    memberships = list(
        await session.scalars(select(Membership).where(Membership.user_id == user_id))
    )
    org_ids = {m.org_id for m in memberships}
    doomed: set[uuid.UUID] = set()
    for membership in memberships:
        other_owners = await count_where(
            session,
            Membership,
            Membership.org_id == membership.org_id,
            Membership.role == OrgRole.owner,
            Membership.user_id != user_id,
        )
        if membership.role == OrgRole.owner and other_owners == 0:
            doomed.add(membership.org_id)
        else:
            await session.delete(membership)
    await session.flush()
    for org_id in org_ids:
        org = await session.get(Organization, org_id)
        if org is None:
            continue
        remaining = await count_where(session, Membership, Membership.org_id == org_id)
        if org_id in doomed or remaining == 0:
            await session.delete(org)
    await session.flush()
