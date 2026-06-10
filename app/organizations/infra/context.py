import uuid

from fastapi import Cookie, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.organizations.infra.repository import OrganizationRepository
from app.shared.database import get_service_session

_COOKIE = "active_org_id"


def set_active_org_cookie(response: Response, org_id: uuid.UUID) -> None:
    response.set_cookie(_COOKIE, str(org_id), httponly=True, samesite="lax")


async def get_current_org(
    current_user: AuthenticatedUser = Depends(get_current_user),
    service_session: AsyncSession = Depends(get_service_session),
    active_org_id: str | None = Cookie(default=None),
) -> uuid.UUID:
    """Résout l'org active : cookie validé contre les memberships, sinon première org."""
    user_uuid = uuid.UUID(current_user.id)
    repo = OrganizationRepository(service_session)

    if active_org_id:
        try:
            org_uuid = uuid.UUID(active_org_id)
        except ValueError:
            org_uuid = None
        if org_uuid:
            membership = await repo.get_membership(org_uuid, user_uuid)
            if membership is not None:
                return org_uuid

    org = await repo.get_first_for_user(user_uuid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organization found")
    return org.id
