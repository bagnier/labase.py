import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.domain.models import Membership, Organization, OrganizationRead, OrgRole
from apps.shared.persistence.database import admin_session_factory


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


async def seed_with_owner(
    org_id: uuid.UUID,
    seed: Callable[[AsyncSession, uuid.UUID], Awaitable[None]],
) -> None:
    """Resolve the org's owner and run ``seed`` in the same session, bailing out silently if
    there's no owner yet (mirrors the todo/calendar/files welcome-data seeders)."""
    async with admin_session_factory()() as session:
        owner_id = await get_org_owner_id(session, org_id)
        if owner_id is None:
            return
        await seed(session, owner_id)
        await session.commit()


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


async def org_handles(
    session: AsyncSession, org_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Map each org id to its URL handle — bulk resolver so callers holding foreign org ids
    (e.g. the console's per-org overrides) never JOIN the organizations table themselves."""
    if not org_ids:
        return {}
    rows = await session.execute(
        select(Organization.id, Organization.handle).where(Organization.id.in_(org_ids))
    )
    return {row.id: row.handle for row in rows}


async def list_org_handles(session: AsyncSession, limit: int = 500) -> list[str]:
    """All org handles, alphabetical — powers the console's org-finder autocomplete
    (a bounded datalist; callers that need every org paginate elsewhere)."""
    rows = await session.execute(
        select(Organization.handle).order_by(Organization.handle).limit(limit)
    )
    return [row.handle for row in rows]


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
