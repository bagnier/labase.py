import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api_keys.domain.models import ApiKey
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository

# ``last_used_at`` is refreshed at most this often, not on every request.
_LAST_USED_GRANULARITY_SECONDS = 300


class ApiKeyRepository(OrgScopedRepository[ApiKey]):
    model = ApiKey
    default_order = ApiKey.created_at.desc()


async def resolve_key_principal(
    session: AsyncSession, key_hash: str
) -> tuple[uuid.UUID, uuid.UUID] | None:
    """``(creator, org)`` of the live key, stamping a stale ``last_used_at``, through the
    ``api_key_principal`` function: no identity exists yet, and no BYPASSRLS read is needed."""
    now = clock.now()
    row = (
        await session.execute(
            text("select created_by, org_id from api_key_principal(:hash, :now, :stale_before)"),
            {
                "hash": key_hash,
                "now": now,
                "stale_before": now - timedelta(seconds=_LAST_USED_GRANULARITY_SECONDS),
            },
        )
    ).first()
    return (row.created_by, row.org_id) if row is not None else None
