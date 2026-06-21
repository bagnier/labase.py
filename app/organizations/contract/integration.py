"""How the organizations context plugs into the running app.

Single composition entry (:func:`register`, called from :mod:`app.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org then scheduling ``OrgCreated`` so
apps can seed welcome data.
"""

import uuid

from fastapi import FastAPI

from app.auth.contract.events import UserCreated
from app.organizations.contract import ORG_PREFIX
from app.organizations.contract.events import OrgCreated
from app.organizations.contract.queries import org_handle_taken
from app.organizations.infra.invitation_router import router as invitation_router
from app.organizations.infra.repository import OrganizationRepository
from app.organizations.infra.router import org_router, router
from app.shared.config import get_settings
from app.shared.host import Host, host
from app.shared.persistence.database import admin_session_factory
from app.shared.slug_registry import register_open_list


def register(app: FastAPI, host: Host) -> None:
    app.include_router(invitation_router)
    app.include_router(router)  # /organizations collection
    app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.on(UserCreated, _create_org)
    host.reserve("invitations")
    register_open_list("organizations", org_handle_taken)


async def _create_org(event: UserCreated) -> None:
    async with admin_session_factory()() as session:
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            auth_user_id=uuid.UUID(event.user_id),
        )
        await session.commit()
    if event.access_token and get_settings().db_schema != "test":
        await host.events.emit(OrgCreated(org_id=org.id, access_token=event.access_token))
