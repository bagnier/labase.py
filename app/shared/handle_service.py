"""Cross-table uniqueness check for handles (users + orgs share a global namespace)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organizations.domain.models import Organization
from app.profile.domain.models import Profile
from app.shared.names import is_reserved


async def handle_is_available(
    handle: str,
    session: AsyncSession,
    *,
    exclude_profile_id: uuid.UUID | None = None,
    exclude_org_id: uuid.UUID | None = None,
) -> bool:
    """Return True if *handle* is not reserved and not taken by any user or org."""
    if is_reserved(handle):
        return False

    profile_q = select(Profile).where(Profile.handle == handle)
    if exclude_profile_id is not None:
        profile_q = profile_q.where(Profile.id != exclude_profile_id)
    if await session.scalar(profile_q) is not None:
        return False

    org_q = select(Organization).where(Organization.handle == handle)
    if exclude_org_id is not None:
        org_q = org_q.where(Organization.id != exclude_org_id)
    return await session.scalar(org_q) is None


async def unique_handle(
    base: str,
    session: AsyncSession,
    *,
    exclude_profile_id: uuid.UUID | None = None,
    exclude_org_id: uuid.UUID | None = None,
) -> str:
    """Return *base* or *base-N* (first available) in the global handle namespace."""
    candidate = base
    n = 2
    while not await handle_is_available(
        candidate,
        session,
        exclude_profile_id=exclude_profile_id,
        exclude_org_id=exclude_org_id,
    ):
        candidate = f"{base}-{n}"
        n += 1
    return candidate
