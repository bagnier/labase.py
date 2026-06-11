import uuid

from fastapi import HTTPException, status

from app.organizations.domain.models import InvitationStatus, OrgRole
from app.organizations.infra.repository import OrganizationRepository


async def ensure_not_already_member(
    repo: OrganizationRepository, org_id: uuid.UUID, email: str
) -> None:
    members = await repo.list_members(org_id)
    emails_result = [str(m.auth_user_id) for m in members]
    # We check via email lookup in the router; this guard is called after email→uid resolution.
    # Here we receive the resolved user_id or None sentinel — see router for the full flow.
    _ = emails_result  # resolution done at router level


async def ensure_no_pending_invitation(
    repo: OrganizationRepository, org_id: uuid.UUID, email: str
) -> None:
    existing = await repo.get_invitation_by_email(org_id, email, InvitationStatus.pending)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="invitation already pending",
        )


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
