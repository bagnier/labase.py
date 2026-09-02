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
    """Whether ``user_id`` still has a row in ``auth.users`` — the seat a reaction writes against
    may have been deleted between the fact being emitted and this durable delivery."""
    return bool(
        await session.scalar(text("SELECT 1 FROM auth.users WHERE id = :id"), {"id": user_id})
    )


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
    """Whether a new organisation gets its welcome content — an admin-tunable setting.

    It used to be a check on the schema name (off wherever the schema was called ``test*``,
    because starter rows would break the other scenarios' assertions). That made a documented
    behaviour — the whole sign-up seeding chain — unreachable by any test in either lane, through
    a branch of production code that existed only for the suite. The suite now turns it off the
    way an admin would, and back on for the scenarios that observe it.
    """
    return get_settings("organizations").seed_welcome_content


async def seed_org_welcome(
    session: AsyncSession,
    org_id: uuid.UUID,
    seed: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]],
) -> None:
    """Run a welcome seeder for a newly created org, on the worker's session.

    Each app registers its seeder as a durable async consumer of ``OrganizationCreated``
    (``consumes_when_enabled``); the listener delivers it and the task worker owns the transaction,
    retry, parking and idempotency. This helper spells the shared boilerplate — resolve the org's
    owner (bail if there isn't one yet), honor the test-schema suppression — so each seeder only
    writes its own welcome rows. No commit: the worker commits the task."""
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
        # The owner can still vanish between the check above and the seeder's own write — the same
        # race the check narrows but cannot close outright. Re-asking after the rollback is what
        # keeps this clause to that one cause: an ``IntegrityError`` names a type, not a
        # constraint, and an owner who never left means the seeder broke something else, which
        # belongs in the worker's retry and eventual park rather than under an ``info`` line.
        await session.rollback()
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
