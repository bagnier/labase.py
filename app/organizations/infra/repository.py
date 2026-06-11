import re
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.domain.models import Membership, OrgRole, Organization


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _unique_slug(self, base: str) -> str:
        slug = base
        n = 2
        while True:
            result = await self.session.execute(
                select(Organization).where(Organization.slug == slug)
            )
            if result.scalars().first() is None:
                return slug
            slug = f"{base}-{n}"
            n += 1

    async def create_with_owner(self, name: str, auth_user_id: uuid.UUID) -> Organization:
        slug = await self._unique_slug(_slugify(name))
        org = Organization(name=name, slug=slug)
        self.session.add(org)
        await self.session.flush()
        membership = Membership(org_id=org.id, auth_user_id=auth_user_id, role=OrgRole.owner)
        self.session.add(membership)
        await self.session.commit()
        return org

    async def list_for_user(self, auth_user_id: uuid.UUID) -> list[Organization]:
        result = await self.session.execute(
            select(Organization)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.auth_user_id == auth_user_id)
        )
        return list(result.scalars().all())

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

    async def get_by_id(self, org_id: uuid.UUID) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.id == org_id))
        return result.scalars().first()

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalars().first()

    async def list_members(self, org_id: uuid.UUID) -> list[Membership]:
        result = await self.session.execute(
            select(Membership).where(Membership.org_id == org_id).order_by(Membership.created_at)
        )
        return list(result.scalars().all())

    async def count_owners(self, org_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(Membership).where(
                Membership.org_id == org_id,
                Membership.role == OrgRole.owner,
            )
        )
        return len(result.scalars().all())

    async def update_member_role(
        self, org_id: uuid.UUID, user_id: uuid.UUID, role: OrgRole
    ) -> Membership | None:
        membership = await self.get_membership(org_id, user_id)
        if membership is None:
            return None
        membership.role = role
        await self.session.commit()
        return membership

    async def remove_member(self, org_id: uuid.UUID, user_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(Membership)
            .where(Membership.org_id == org_id, Membership.auth_user_id == user_id)
            .returning(Membership.auth_user_id)
        )
        await self.session.commit()
        return result.scalar() is not None

    async def rename(self, org: Organization, name: str) -> None:
        org.name = name
        await self.session.commit()
