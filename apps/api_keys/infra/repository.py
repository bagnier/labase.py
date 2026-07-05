from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api_keys.domain.models import ApiKey
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository

# last_used_at is informational; refresh it at most this often to avoid a write per request.
_LAST_USED_GRANULARITY_SECONDS = 300


class ApiKeyRepository(OrgScopedRepository[ApiKey]):
    model = ApiKey
    default_order = ApiKey.created_at.desc()


async def resolve_active_key(session: AsyncSession, key_hash: str) -> ApiKey | None:
    """The non-revoked key matching `key_hash` — admin session, pre-auth surface."""
    key = await session.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
    if key is None or key.revoked_at is not None:
        return None
    return key


async def touch_last_used(session: AsyncSession, key: ApiKey) -> None:
    now = clock.now()
    stale = key.last_used_at is None or (
        (now - key.last_used_at).total_seconds() > _LAST_USED_GRANULARITY_SECONDS
    )
    if stale:
        key.last_used_at = now
        await session.flush()
