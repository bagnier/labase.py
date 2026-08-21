"""How the organizations context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org then emitting ``OrganizationCreated``
— the journal record that also triggers the welcome seeders.
"""

import uuid

import structlog
from sqlalchemy import select, text
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
from apps.organizations.contract.queries import org_handle_taken
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

# Mounts the org-scoped catch-all router under /{org_handle}; the composition root mounts such
# contexts last (see apps.main) so fixed-prefix routers (e.g. /console) are never shadowed.


def mount(host: Host) -> None:
    # Core context (owns /{org_handle}); never gated off, so it declares no on/off switch.
    host.register_settings(_declare_settings())
    host.app.include_router(invitation_router)
    host.app.include_router(router)  # /organizations collection
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
    host.register_fullpage_provider("org", provide_org_nav)
    host.register_nav(
        NavItem("Settings", "gear", "settings", "/settings", order=110, owner_only=True)
    )
    # Both top-level paths this context routes: `/organizations` (the list) and
    # `/invitations/{token}` (the accept link). An org handle taking either would leave one of
    # the two unreachable — the list is the one it would shadow at its own name.
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
        # No "growth" slice: every sign-up auto-creates a personal org, so orgs-per-day
        # would just shadow the Sign-ups series on the console growth chart. Team creation
        # isn't structurally distinguishable from a personal org, so we don't fake a signal.
        data={"lines": lines},
    )


async def _create_org(session: AsyncSession, event: UserCreated) -> None:
    """Durable consumer of ``UserCreated``: create the user's personal org, then emit
    ``OrganizationCreated`` (the fact the welcome seeders react to). Runs off the journal on the
    worker's session — the worker commits the org and the emitted fact together, so the seeders
    (delivered after that commit) always read the org back. Idempotent (the ``already_member``
    guard), so a task retry never double-creates."""
    if not get_settings("organizations").auto_create_personal_org:
        return
    user_id = event.user_id
    if user_id is None:
        return
    # A business event is an immutable fact, not a saga step: the actor may be gone by the time this
    # durable consumer runs (self-deletion between emit and delivery). Seat off ``auth.users`` — no
    # user, no org — so a vanished subject is a clean no-op, not an FK crash + park.
    exists = await session.scalar(text("SELECT 1 FROM auth.users WHERE id = :id"), {"id": user_id})
    if not exists:
        log.info("create_personal_org.actor_gone", user_id=str(user_id))
        return
    already_member = await count_where(session, Membership, Membership.user_id == user_id)
    if already_member:
        return  # returning user — OAuth sign-ins re-emit UserCreated on every visit
    org = await OrganizationRepository(session).create_with_owner(
        name=event.email,
        user_id=user_id,
    )
    await session.flush()  # assign org.id; the worker commits the whole unit
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
    """Account deletion: drop the user's memberships, reaping any org the departure
    would leave without an owner (nobody could run it) or without any member.

    A durable async consumer of ``UserDeleted`` (run on the admin session off the listener, keyed on
    the removed user's ``entity_id``), so cleanup never sits on the deleting request's path and is
    retried/parked on failure. A last-owner seat is not deleted directly — the DB guard forbids
    orphaning an org, and deleting it would strand any remaining members in an ownerless org — so we
    reap the whole org instead (SQL cascade takes its memberships and org-scoped rows, and the
    cascade's own membership deletes are exempt from the guard because the org is already gone).
    """
    # entity_id is the removed user's pk (a uuid, re-parsed by from_payload). Defensive no-op if a
    # malformed row ever carries none.
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
        # Losing the last owner leaves the org unmanageable — reap it whole rather than
        # delete this seat (which the guard would refuse anyway). Otherwise drop the seat.
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
