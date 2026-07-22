"""How the organizations context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org then emitting ``OrganizationCreated``
— the trail record that also triggers the welcome seeders.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.events import UserCreated, UserDeleted
from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.fullpage import provide_org_nav
from apps.organizations.contract.queries import org_handle_taken
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.invitation_router import router as invitation_router
from apps.organizations.infra.repository import OrganizationRepository
from apps.organizations.infra.router import org_router, router
from apps.shared.events.bus import events
from apps.shared.events.outbox import on_async
from apps.shared.host import Host, MountPhase, NavItem
from apps.shared.persistence.database import admin_session_factory
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, get_settings
from apps.shared.text import pluralize

PHASE = MountPhase.ORG

# Mounts the org-scoped catch-all router under /{org_handle}; the composition root mounts such
# contexts last (see apps.main) so fixed-prefix routers (e.g. /console) are never shadowed.


def mount(host: Host) -> None:
    # Core context (owns /{org_handle}); never gated off, so it declares no on/off switch.
    host.register_settings(_declare_settings())
    host.app.include_router(invitation_router)
    host.app.include_router(router)  # /organizations collection
    host.app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.on(UserCreated, _create_org)
    on_async(UserDeleted, "organizations_forget", _forget_user, as_actor=False, idempotent=True)
    host.contribs.provide(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("org", provide_org_nav)
    host.register_nav(
        NavItem("Settings", "gear", "settings", "/settings", order=110, owner_only=True)
    )
    host.reserve("invitations")
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
                "max_invitations_per_org",
                "number",
                "-1",
                "Max pending invitations per organisation (-1 = unlimited)",
            ),
        ],
        supabase=SupabaseLink("Browse organisations in Supabase", table="organizations"),
    )


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    orgs = await query.session.scalar(select(func.count()).select_from(Organization)) or 0
    members = await query.session.scalar(select(func.count()).select_from(Membership)) or 0
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


async def _create_org(event: UserCreated) -> None:
    if not get_settings("organizations").auto_create_personal_org:
        return
    user_id = uuid.UUID(event.actor_id)
    async with admin_session_factory()() as session:
        already_member = await session.scalar(
            select(func.count()).select_from(Membership).where(Membership.auth_user_id == user_id)
        )
        if already_member:
            return  # returning user — OAuth sign-ins re-emit UserCreated on every visit
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            auth_user_id=user_id,
        )
        await session.commit()
    # Committed above so the seeders (each on its own admin session) can read the org back.
    await events.emit(
        OrganizationCreated(
            actor_id=str(user_id),
            org_id=str(org.id),
            entity_id=str(org.id),
            label=org.name,
        )
    )


async def _forget_user(session: AsyncSession, event: UserDeleted) -> None:
    """Account deletion: drop the user's memberships, reaping any org the departure
    would leave without an owner (nobody could run it) or without any member.

    A durable async consumer of ``UserDeleted`` (run on the admin session off the tailer, keyed on
    the removed user's ``entity_id``), so cleanup never sits on the deleting request's path and is
    retried/parked on failure. A last-owner seat is not deleted directly — the DB guard forbids
    orphaning an org, and deleting it would strand any remaining members in an ownerless org — so we
    reap the whole org instead (SQL cascade takes its memberships and org-scoped rows, and the
    cascade's own membership deletes are exempt from the guard because the org is already gone).
    """
    user_id = uuid.UUID(event.entity_id)
    memberships = list(
        await session.scalars(select(Membership).where(Membership.auth_user_id == user_id))
    )
    org_ids = {m.org_id for m in memberships}
    doomed: set[uuid.UUID] = set()
    for membership in memberships:
        other_owners = (
            await session.scalar(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.org_id == membership.org_id,
                    Membership.role == OrgRole.owner,
                    Membership.auth_user_id != user_id,
                )
            )
            or 0
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
        remaining = (
            await session.scalar(
                select(func.count()).select_from(Membership).where(Membership.org_id == org_id)
            )
            or 0
        )
        if org_id in doomed or remaining == 0:
            await session.delete(org)
    await session.flush()
