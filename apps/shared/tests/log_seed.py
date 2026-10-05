"""Lines written straight to ``log_lines``, for tests needing a line no code path produces, and
a way to empty the shared store."""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared import clock
from apps.shared.logs.models import LogLine
from apps.shared.logs.repository import LogRepository


async def seed_log_line(
    session: AsyncSession,
    event: str,
    *,
    logger: str = "apps.shared.tests",
    level: str = "info",
    ts: datetime | None = None,
    instance: str = "test",
    **fields: object,
) -> None:
    line = {
        "event": event,
        "logger": logger,
        "level": level,
        "timestamp": (ts or clock.now()).isoformat(),
        **fields,
    }
    await LogRepository(session).append([line], instance=instance)
    await session.commit()


async def clear_log_lines(session: AsyncSession) -> None:
    await session.execute(delete(LogLine))
    await session.commit()
