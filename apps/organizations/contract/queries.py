import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.domain.models import Membership, Organization, OrganizationRead, OrgRole
from apps.shared.settings.live import get_settings

log = structlog.get_logger(__name__)


async def user_exists(session: AsyncSession, user_id: uuid.UUID) -> bool:
    """For a reaction whose user may have been deleted since the fact."""
    return bool(
        await session.scalar(text("SELECT 1 FROM auth.users WHERE id = :id"), {"id": user_id})
    )


async def org_exists(session: AsyncSession, org_id: uuid.UUID) -> bool:
    """For a reaction whose org may have been deleted since the fact."""
    row = await session.scalar(select(Organization.id).where(Organization.id == org_id))
    return row is not None


async def org_handle_taken(
    session: AsyncSession, handle: str, exclude_id: uuid.UUID | None = None
) -> bool:
    q = select(Organization).where(Organization.handle == handle)
    if exclude_id is not None:
        q = q.where(Organization.id != exclude_id)
    return await session.scalar(q) is not None


async def get_org_owner_id(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID | None:
    return await session.scalar(
        select(Membership.user_id).where(
            Membership.org_id == org_id, Membership.role == OrgRole.owner
        )
    )


def seeding_enabled() -> bool:
    """A setting; the suite turns it off like an admin would, except where seeding is tested."""
    return get_settings("organizations").seed_welcome_content


async def seed_org_welcome(
    session: AsyncSession,
    org_id: uuid.UUID,
    seed: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]],
) -> None:
    """Run an app's welcome ``seed`` for a new org on the worker's session, with its owner; a
    no-op when seeding is off or the owner is gone. The worker commits."""
    if not seeding_enabled():
        return
    owner_id = await get_org_owner_id(session, org_id)
    if owner_id is None:
        return
    if not await user_exists(session, owner_id):
        log.info("seed_org_welcome.actor_gone", owner_id=str(owner_id))
        return
    try:
        await seed(session, org_id, owner_id)
    except IntegrityError:
        # The owner or org may vanish meanwhile; if both remain, the failure is something else,
        # for the worker to retry then park.
        await session.rollback()
        if not await org_exists(session, org_id):
            log.info("seed_org_welcome.org_gone", org_id=str(org_id))
            return
        if await user_exists(session, owner_id):
            raise
        log.info("seed_org_welcome.actor_gone", owner_id=str(owner_id))


@dataclass
class UserOrgSummary:
    id: uuid.UUID
    name: str
    handle: str
    is_owner: bool


async def org_by_handle(session: AsyncSession, handle: str) -> OrganizationRead | None:
    """By handle, ignoring RLS, for public routes."""
    org = await session.scalar(select(Organization).where(Organization.handle == handle))
    return OrganizationRead.model_validate(org) if org is not None else None


async def org_handles(
    session: AsyncSession, org_ids: Collection[uuid.UUID]
) -> dict[uuid.UUID, str]:
    """Org id → handle in bulk, so other contexts never JOIN ``organizations``."""
    if not org_ids:
        return {}
    rows = await session.execute(
        select(Organization.id, Organization.handle).where(Organization.id.in_(org_ids))
    )
    return {row.id: row.handle for row in rows}


async def list_org_handles(session: AsyncSession, limit: int = 500) -> list[str]:
    """Org handles, alphabetical, for the console's autocomplete."""
    rows = await session.execute(
        select(Organization.handle).order_by(Organization.handle).limit(limit)
    )
    return [row.handle for row in rows]


async def role_in_org(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> OrgRole | None:
    return await session.scalar(
        select(Membership.role).where(Membership.org_id == org_id, Membership.user_id == user_id)
    )


async def get_user_orgs(session: AsyncSession, user_id: uuid.UUID) -> list[UserOrgSummary]:
    rows = (
        await session.execute(
            select(Organization, Membership.role)
            .join(Membership, Membership.org_id == Organization.id)
            .where(Membership.user_id == user_id)
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
