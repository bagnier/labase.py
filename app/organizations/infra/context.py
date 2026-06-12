import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.organizations.domain.models import Membership
from app.organizations.infra.repository import OrganizationRepository
from app.shared.persistence.database import get_admin_session


async def get_current_org(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> uuid.UUID:
    """Resolve org from {org_slug} path parameter."""
    user_uuid = uuid.UUID(current_user.id)
    repo = OrganizationRepository(admin_session)

    slug = request.path_params.get("org_slug")
    if slug:
        org = await repo.get_by_slug(slug)
        if org is not None:
            membership = await repo.get_membership(org.id, user_uuid)
            if membership is not None:
                return org.id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Organisation not found or access denied"
        )

    # Fallback for routes not under /orgs/{org_slug}: use first org
    org = await repo.get_first_for_user(user_uuid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organization found")
    return org.id


async def get_current_membership(
    current_user: AuthenticatedUser = Depends(get_current_user),
    admin_session: AsyncSession = Depends(get_admin_session),
    org_id: uuid.UUID = Depends(get_current_org),
) -> Membership:
    user_uuid = uuid.UUID(current_user.id)
    repo = OrganizationRepository(admin_session)
    membership = await repo.get_membership(org_id, user_uuid)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member")
    return membership
