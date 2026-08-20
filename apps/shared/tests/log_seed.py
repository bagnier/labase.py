"""Seeding ``log_lines`` directly — for tests that need a log line without logging one.

The twin of :mod:`apps.shared.tests.journal_seed`. Production fills this table exactly one way:
the structlog processor enqueues, the ``LogDrain`` batches. A test often needs the opposite — a
line of some logger's, at some level, dated last week, with no code path that would produce it.

It also has to *clear*: the store is shared and committed, where the per-day files it replaced
gave every test a scratch directory for free. A test asserting "these are the log entries" has to
say which run they belong to, or start from empty.
"""

from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared import clock
from apps.shared.observability.models import LogLine
from apps.shared.observability.repository import LogRepository


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
    """Append one line and commit — the arrangement has to outlive the request under test."""
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
    """Empty the store, so a test that asserts over *all* log entries means its own."""
    await session.execute(delete(LogLine))
    await session.commit()
