import uuid

from sqlalchemy import delete, func, select, text

from apps.organizations.domain.models import (
    InvitationStatus,
    Membership,
    Organization,
    OrgInvitation,
    OrgRole,
)
from apps.shared.persistence.repository import BaseRepository
from apps.shared.slug_registry import handle_is_available, slugify, unique_handle


class OrganizationRepository(BaseRepository[Organization]):
    model = Organization

    async def create_with_owner(
        self,
        name: str,
        auth_user_id: uuid.UUID,
        suggested_handle: str | None = None,
    ) -> Organization:
        base = suggested_handle if suggested_handle else slugify(name)
        if not base:
            base = "org"
        handle = await unique_handle(base, self.session)
        org = Organization(name=name, handle=handle)
        self.session.add(org)
        await self.session.flush()
        membership = Membership(org_id=org.id, auth_user_id=auth_user_id, role=OrgRole.owner)
        self.session.add(membership)
        await self.session.flush()

        return org

    async def list_with_role_for_user(
        self, auth_user_id: uuid.UUID
    ) -> list[tuple[Organization, OrgRole]]:
        result = await self.session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.auth_user_id == auth_user_id)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def get_membership(self, org_id: uuid.UUID, auth_user_id: uuid.UUID) -> Membership | None:
        result = await self.session.execute(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.auth_user_id == auth_user_id,
            )
        )
        return result.scalars().first()

    async def get_first_for_user(self, auth_user_id: uuid.UUID) -> Organization | None:
        result = await self.session.execute(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.auth_user_id == auth_user_id)
            .order_by(Organization.created_at)
            .limit(1)
        )
        return result.scalars().first()

    async def get_by_handle(self, handle: str) -> Organization | None:
        return await self.session.scalar(select(Organization).where(Organization.handle == handle))

    async def get_by_handle_for_user(
        self, handle: str, auth_user_id: uuid.UUID
    ) -> Organization | None:
        return await self.session.scalar(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Organization.handle == handle, Membership.auth_user_id == auth_user_id)
        )

    async def is_handle_available(self, handle: str, org_id: uuid.UUID) -> bool:
        return await handle_is_available(
            handle, self.session, exclude_from="organizations", exclude_id=org_id
        )

    async def list_members(self, org_id: uuid.UUID) -> list[Membership]:
        result = await self.session.execute(
            select(Membership).where(Membership.org_id == org_id).order_by(Membership.created_at)
        )
        return list(result.scalars().all())

    async def count_owners(self, org_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.org_id == org_id,
                Membership.role == OrgRole.owner,
            )
        )
        return result.scalar_one()

    async def update_member_role(
        self, org_id: uuid.UUID, user_id: uuid.UUID, role: OrgRole
    ) -> Membership | None:
        membership = await self.get_membership(org_id, user_id)
        if membership is None:
            return None
        membership.role = role

        return membership

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(Membership)
            .where(Membership.org_id == org_id, Membership.auth_user_id == user_id)
            .returning(Membership.auth_user_id)
        )

        return result.scalar() is not None

    async def rename(self, org: Organization, name: str) -> None:
        org.name = name

    async def update_handle(self, org: Organization, handle: str) -> None:
        org.handle = handle

    async def create_invitation(
        self, org_id: uuid.UUID, email: str, role: OrgRole, invited_by: uuid.UUID
    ) -> OrgInvitation:
        invitation = OrgInvitation(org_id=org_id, email=email, role=role, invited_by=invited_by)
        self.session.add(invitation)
        await self.session.flush()
        return invitation

    async def list_invitations(
        self, org_id: uuid.UUID, status: InvitationStatus = InvitationStatus.pending
    ) -> list[OrgInvitation]:
        result = await self.session.execute(
            select(OrgInvitation)
            .where(OrgInvitation.org_id == org_id, OrgInvitation.status == status)
            .order_by(OrgInvitation.created_at)
        )
        return list(result.scalars().all())

    async def get_invitation_by_email(
        self, org_id: uuid.UUID, email: str, status: InvitationStatus = InvitationStatus.pending
    ) -> OrgInvitation | None:
        result = await self.session.execute(
            select(OrgInvitation).where(
                OrgInvitation.org_id == org_id,
                OrgInvitation.email == email,
                OrgInvitation.status == status,
            )
        )
        return result.scalars().first()

    async def get_invitation_by_id(
        self, org_id: uuid.UUID, invitation_id: uuid.UUID
    ) -> OrgInvitation | None:
        result = await self.session.execute(
            select(OrgInvitation).where(
                OrgInvitation.id == invitation_id,
                OrgInvitation.org_id == org_id,
            )
        )
        return result.scalars().first()

    async def revoke_invitation(self, invitation: OrgInvitation) -> None:
        invitation.status = InvitationStatus.revoked

    async def get_invitation_by_token(self, token: uuid.UUID) -> dict | None:
        result = await self.session.execute(
            text("SELECT * FROM public.get_invitation_by_token(:token)"),
            {"token": str(token)},
        )
        row = result.mappings().first()
        return dict(row) if row is not None else None

    async def accept_org_invitation(self, token: uuid.UUID) -> None:
        """Must be called with an RLS session so auth.uid() is set from the JWT."""
        await self.session.execute(
            text("SELECT public.accept_org_invitation(:token)"),
            {"token": str(token)},
        )
