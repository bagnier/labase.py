import uuid

from fastapi import HTTPException, status

from app.organizations.domain.models import OrgRole
from app.organizations.infra.repository import OrganizationRepository


async def ensure_not_last_owner(
    repo: OrganizationRepository, org_id: uuid.UUID, target_user_id: uuid.UUID
) -> None:
    membership = await repo.get_membership(org_id, target_user_id)
    if membership is None or membership.role != OrgRole.owner:
        return
    owner_count = await repo.count_owners(org_id)
    if owner_count <= 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot remove or demote the last owner",
        )
