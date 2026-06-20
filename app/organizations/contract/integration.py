"""How the organizations context plugs into the running app.

Single composition entry (:func:`register`, called from :mod:`app.main`): mounts the
collection, invitation and org-scoped routers, claims the ``invitations`` slug, and reacts to
auth's ``UserCreated`` by creating the user's personal org. The created ``org_id`` is returned
so the registration orchestrator can chain the downstream ``OrgCreated`` event (seeding).
"""

import uuid

from fastapi import FastAPI

from app.auth.contract.events import UserCreated
from app.integration import Host
from app.organizations.contract import ORG_PREFIX
from app.organizations.infra.invitation_router import router as invitation_router
from app.organizations.infra.repository import OrganizationRepository
from app.organizations.infra.router import org_router, router
from app.shared.persistence.database import admin_session_factory


def register(app: FastAPI, host: Host) -> None:
    app.include_router(invitation_router)
    app.include_router(router)  # /organizations collection
    app.include_router(org_router, prefix=ORG_PREFIX)
    host.events.on(UserCreated, _create_org)
    host.reserve("invitations")


async def _create_org(event: UserCreated) -> uuid.UUID:
    async with admin_session_factory()() as session:
        org = await OrganizationRepository(session).create_with_owner(
            name=event.email,
            auth_user_id=uuid.UUID(event.user_id),
        )
        await session.commit()
        return org.id
