"""How the organizations context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`app.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org then scheduling ``OrgCreated`` so
apps can seed welcome data.
"""

import uuid

from fastapi import FastAPI
from sqlalchemy import func, select

from app.auth.contract.events import UserCreated
from app.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from app.console.contract.settings import (
    ConsoleSettingsQuery,
    SettingsGroup,
    SupabaseLink,
    get_app_settings,
)
from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.queries import org_handle_taken
from app.organizations.domain.models import Membership, Organization
from app.organizations.infra.invitation_router import router as invitation_router
from app.organizations.infra.repository import OrganizationRepository
from app.organizations.infra.router import org_router, router
from app.shared.config import get_technical_settings
from app.shared.host import Host, NavItem, host
from app.shared.persistence.database import admin_session_factory
from app.shared.slug_registry import register_open_list

# Mounts the org-scoped catch-all router under /{org_handle}; the composition root mounts such
# contexts last (see app.main) so fixed-prefix routers (e.g. /console) are never shadowed.


def mount(app: FastAPI, host: Host) -> None:
    # Read this context's persisted settings like every app does at mount. Organizations is the
    # core context (owns /{org_handle}); it is never gated off, so the switch is not consulted.
    get_app_settings("organizations")
    app.include_router(invitation_router)
    app.include_router(router)  # /organizations collection
    app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.on(UserCreated, _create_org)
    host.events.on(ConsoleOverviewQuery, _console_overview)
    host.events.on(ConsoleSettingsQuery, _console_settings)
    host.register_nav(
        NavItem("Settings", "gear", "settings", "/settings", order=100, owner_only=True)
    )
    host.reserve("invitations")
    register_open_list("organizations", org_handle_taken)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    orgs = await query.session.scalar(select(func.count()).select_from(Organization)) or 0
    members = await query.session.scalar(select(func.count()).select_from(Membership)) or 0
    if orgs:
        lines = [f"{orgs} organisation" + ("s" if orgs > 1 else ""), f"{members} members"]
    else:
        lines = ["No organisations yet"]
    return ConsoleOverview(
        key="organizations", title="Organisations", icon="buildings", data={"lines": lines}
    )


async def _console_settings(query: ConsoleSettingsQuery) -> SettingsGroup:
    return SettingsGroup(
        app="organizations",
        supabase=SupabaseLink("Browse organisations in Supabase", table="organizations"),
    )


async def _create_org(event: UserCreated) -> None:
    async with admin_session_factory()() as session:
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            auth_user_id=uuid.UUID(event.user_id),
        )
        await session.commit()
    if event.access_token and get_technical_settings().db_schema != "test":
        await host.events.emit(OrgCreated(org_id=org.id, access_token=event.access_token))
