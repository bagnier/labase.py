import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.domain.models import Membership, Organization, OrganizationRead, OrgRole


async def org_handle_taken(
    session: AsyncSession, handle: str, exclude_id: uuid.UUID | None = None
) -> bool:
    q = select(Organization).where(Organization.handle == handle)
    if exclude_id is not None:
        q = q.where(Organization.id != exclude_id)
    return await session.scalar(q) is not None


async def get_org_owner_id(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Membership.auth_user_id).where(
            Membership.org_id == org_id, Membership.role == OrgRole.owner
        )
    )


@dataclass
class UserOrgSummary:
    id: uuid.UUID
    name: str
    handle: str
    is_owner: bool


async def org_by_handle(session: AsyncSession, handle: str) -> OrganizationRead | None:
    """Resolve an org by its URL handle, ignoring RLS — used by public-facing routes."""
    org = await session.scalar(select(Organization).where(Organization.handle == handle))
    return OrganizationRead.model_validate(org) if org is not None else None


async def role_in_org(
    session: AsyncSession, org_id: uuid.UUID, auth_user_id: uuid.UUID
) -> OrgRole | None:
    return await session.scalar(
        select(Membership.role).where(
            Membership.org_id == org_id, Membership.auth_user_id == auth_user_id
        )
    )


async def get_user_orgs(session: AsyncSession, user_id: uuid.UUID) -> list[UserOrgSummary]:
    rows = (
        await session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.auth_user_id == user_id)
            .order_by(Organization.created_at)
        )
    ).all()
    return [
        UserOrgSummary(
            id=row[0].id,
            name=row[0].name,
            handle=row[0].handle,
            is_owner=row[1] == OrgRole.owner,
        )
        for row in rows
    ]
