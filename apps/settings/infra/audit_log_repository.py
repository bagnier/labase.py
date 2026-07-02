from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

AUDIT_LOG_COLUMNS = "id, created_at, level, event, user_id, ip, payload"


class AuditLogRepository:
    """Read-only, cursor-paginated access to the append-only ``audit_logs`` table.

    Every query is bounded (``LIMIT``) — the table can grow unbounded, so nothing here
    ever loads it whole. ``search`` fetches one row past ``limit`` so the caller can tell
    whether an older page exists without a separate COUNT.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def count(self) -> int:
        return await self.session.scalar(text("SELECT COUNT(*) FROM audit_logs")) or 0

    async def search(
        self,
        *,
        level: str | None = None,
        event: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        before_id: int | None = None,
        limit: int = 50,
    ) -> list[dict]:
        rows = await self.session.execute(
            # Explicit CASTs — asyncpg can't infer a parameter's type when every bound
            # value is NULL (e.g. loading the page with no filters set at all).
            text(
                f"SELECT {AUDIT_LOG_COLUMNS} FROM audit_logs "
                "WHERE (CAST(:level AS text) IS NULL OR level = :level) "
                "AND (CAST(:event AS text) IS NULL OR event ILIKE :event) "
                "AND (CAST(:from_dt AS timestamptz) IS NULL OR created_at >= :from_dt) "
                "AND (CAST(:to_dt AS timestamptz) IS NULL OR created_at <= :to_dt) "
                "AND (CAST(:before_id AS bigint) IS NULL OR id < :before_id) "
                "ORDER BY id DESC LIMIT :fetch_limit"
            ),
            {
                "level": level,
                "event": f"%{event}%" if event else None,
                "from_dt": from_dt,
                "to_dt": to_dt,
                "before_id": before_id,
                "fetch_limit": limit + 1,
            },
        )
        return [dict(row) for row in rows.mappings()]


def parse_range_bound(value: str) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value, treated as UTC."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)
