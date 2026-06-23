import uuid
from typing import Protocol

from apps.organizations.domain.models import InvitationStatus, Membership, OrgInvitation


class OrganizationRepositoryProtocol(Protocol):
    async def get_invitation_by_email(
        self, org_id: uuid.UUID, email: str, status: InvitationStatus
    ) -> OrgInvitation | None: ...

    async def get_membership(
        self, org_id: uuid.UUID, auth_user_id: uuid.UUID
    ) -> Membership | None: ...

    async def count_owners(self, org_id: uuid.UUID) -> int: ...
