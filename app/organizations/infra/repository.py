import uuid

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.organizations.domain.models import Membership, OrgRole, Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_with_owner(self, name: str, auth_user_id: uuid.UUID) -> Organization:
        org = Organization(name=name)
        self.session.add(org)
        await self.session.flush()
        membership = Membership(org_id=org.id, auth_user_id=auth_user_id, role=OrgRole.owner)
        self.session.add(membership)
        await self.session.commit()
        return org

    async def list_for_user(self, auth_user_id: uuid.UUID) -> list[Organization]:
        result = await self.session.exec(
            select(Organization)
            .join(Membership, col(Membership.org_id) == col(Organization.id))
            .where(Membership.auth_user_id == auth_user_id)
        )
        return list(result.all())

    async def get_membership(self, org_id: uuid.UUID, auth_user_id: uuid.UUID) -> Membership | None:
        result = await self.session.exec(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.auth_user_id == auth_user_id,
            )
        )
        return result.first()

    async def get_first_for_user(self, auth_user_id: uuid.UUID) -> Organization | None:
        result = await self.session.exec(
            select(Organization)
            .join(Membership, col(Membership.org_id) == col(Organization.id))
            .where(Membership.auth_user_id == auth_user_id)
            .order_by(col(Organization.created_at))
            .limit(1)
        )
        return result.first()
