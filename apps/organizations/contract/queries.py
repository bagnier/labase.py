import asyncio
import uuid
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.domain.models import Membership, Organization, OrganizationRead, OrgRole
from apps.shared.config import get_technical_settings
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.organizations.seeding")


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


def seeding_enabled() -> bool:
    """Welcome seeding runs everywhere except the test schema, where the browser E2E driver
    truncates app tables between scenarios and starter rows would break their assertions."""
    return get_technical_settings().supabase_database_schema != "test"


def spawn_org_seed(
    org_id: str | None,
    seed: Callable[[AsyncSession, uuid.UUID, uuid.UUID], Awaitable[None]],
) -> None:
    """Fire-and-forget welcome seeding for a newly created org.

    Opens a fresh admin session, resolves the org's owner (bailing if there isn't one yet), runs
    ``seed(session, org_id, owner_id)`` and commits — so each seeder only spells its own welcome
    rows, never the session/owner/commit boilerplate.

    Scheduled off the emit: seeders react to ``OrganizationCreated`` but must never sit on the
    mutation's critical path, nor let a failure break org creation — being earlier in the bus MRO
    than the trail persister, a raised seeder would also suppress the trail write. Failures are
    logged, mirroring the business-event persister's doctrine. Suppressed in the test schema."""
    if not seeding_enabled() or not org_id:
        return
    resolved = uuid.UUID(org_id)

    async def run() -> None:
        try:
            async with admin_session_factory()() as session:
                owner_id = await get_org_owner_id(session, resolved)
                if owner_id is None:
                    return
                await seed(session, resolved, owner_id)
                await session.commit()
        except Exception:
            log.exception("organizations.seed_failed", org_id=org_id)

    asyncio.create_task(run())


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
