"""How the organizations context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org then scheduling ``OrgCreated`` so
apps can seed welcome data.
"""

import uuid

from sqlalchemy import func, select

from apps.auth.contract.events import UserCreated
from apps.organizations.contract import ORG_PREFIX, settings
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.fullpage import provide_org_nav
from apps.organizations.contract.queries import org_handle_taken
from apps.organizations.domain.models import Membership, Organization
from apps.organizations.infra.invitation_router import router as invitation_router
from apps.organizations.infra.repository import OrganizationRepository
from apps.organizations.infra.router import org_router, router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
)
from apps.shared.config import get_technical_settings
from apps.shared.host import Host, NavItem, host
from apps.shared.persistence.database import admin_session_factory
from apps.shared.slug_registry import register_open_list

# Mounts the org-scoped catch-all router under /{org_handle}; the composition root mounts such
# contexts last (see apps.main) so fixed-prefix routers (e.g. /console) are never shadowed.


def mount(host: Host) -> None:
    # Core context (owns /{org_handle}); never gated off, so it declares no on/off switch.
    settings.group = declare_app_settings(
        "organizations",
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
        ],
        supabase=SupabaseLink("Browse organisations in Supabase", table="organizations"),
    )
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.app.include_router(invitation_router)
    host.app.include_router(router)  # /organizations collection
    host.app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.on(UserCreated, _create_org)
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.register_fullpage_provider("org", provide_org_nav)
    host.register_nav(
        NavItem("Settings", "gear", "settings", "/settings", order=100, owner_only=True)
    )
    host.reserve("invitations")
    register_open_list("organizations", org_handle_taken)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    orgs = await query.session.scalar(select(func.count()).select_from(Organization)) or 0
    members = await query.session.scalar(select(func.count()).select_from(Membership)) or 0
    if orgs:
        noun_o = "organisation" + ("s" if orgs != 1 else "")
        noun_m = "member" + ("s" if members != 1 else "")
        lines = [f"{orgs} {noun_o}", f"{members} {noun_m}"]
    else:
        lines = ["No organisations yet"]
    return ConsoleOverview(
        key="organizations", title="Organisations", icon="buildings", data={"lines": lines}
    )


async def _create_org(event: UserCreated) -> None:
    if not settings.auto_create_personal_org:
        return
    async with admin_session_factory()() as session:
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            auth_user_id=uuid.UUID(event.user_id),
        )
        await session.commit()
    if event.access_token and get_technical_settings().supabase_database_schema != "test":
        await host.events.emit(OrgCreated(org_id=org.id, access_token=event.access_token))
