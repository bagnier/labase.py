import uuid

from app.organizations.domain.exceptions import LastOwnerViolation, PendingInvitationExists
from app.organizations.domain.models import InvitationStatus, OrgRole
from app.organizations.domain.repository import OrganizationRepositoryProtocol


async def ensure_no_pending_invitation(
    repo: OrganizationRepositoryProtocol, org_id: uuid.UUID, email: str
) -> None:
    existing = await repo.get_invitation_by_email(org_id, email, InvitationStatus.pending)
    if existing is not None:
        raise PendingInvitationExists("invitation already pending")


async def ensure_not_last_owner(
    repo: OrganizationRepositoryProtocol, org_id: uuid.UUID, target_user_id: uuid.UUID
) -> None:
    membership = await repo.get_membership(org_id, target_user_id)
    if membership is None or membership.role != OrgRole.owner:
        return
    owner_count = await repo.count_owners(org_id)
    if owner_count <= 1:
        raise LastOwnerViolation("Cannot remove or demote the last owner")
