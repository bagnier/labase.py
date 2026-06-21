import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.profile.domain.models import Profile


async def profile_handle_taken(
    session: AsyncSession, handle: str, exclude_id: uuid.UUID | None = None
) -> bool:
    q = select(Profile).where(Profile.handle == handle)
    if exclude_id is not None:
        q = q.where(Profile.id != exclude_id)
    return await session.scalar(q) is not None
