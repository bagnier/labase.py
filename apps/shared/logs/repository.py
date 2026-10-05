"""Every query against ``log_lines``: the drain's batch append, the Timeline's read, retention.
How lines get here is :mod:`apps.shared.logs.sink`'s job.
"""

import json
import uuid
from collections.abc import Collection
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from sqlalchemy import String, Text, cast, extract, func, insert, or_, select
from sqlalchemy import text as sql_text  # aliased: ``search`` takes a ``text`` filter of its own

from apps.shared import clock
from apps.shared.logs.models import LogLine
from apps.shared.persistence.repository import BaseRepository

# Bounds an unfiltered Timeline read; not retention.
DEFAULT_WINDOW = timedelta(days=2)

# This process, for the ``instance`` column.
INSTANCE = uuid.uuid4().hex[:8]

# Event-dict keys promoted to first-class columns; everything else lands in ``payload``.
_RESERVED = {"timestamp", "level", "logger", "event", "org_id", "user_id", "request_id"}

# asyncpg's cap on one statement's bound parameters (a 16-bit count in the wire protocol). A full
# queue holds more lines than one multi-row ``VALUES`` can bind.
_MAX_STATEMENT_PARAMS = 32767


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value)
    else:
        ts = clock.now()
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _as_text(value: Any) -> str | None:
    return None if value is None else str(value)


def _columns(line: dict[str, Any], instance: str) -> dict[str, Any]:
    return {
        "ts": _parse_ts(line.get("timestamp")),
        "level": str(line.get("level") or "info"),
        "logger": str(line.get("logger") or ""),
        "name": str(line.get("event") or ""),
        "org_id": _as_text(line.get("org_id")),
        "user_id": _as_text(line.get("user_id")),
        "request_id": _as_text(line.get("request_id")),
        "instance": instance,
        # ``default=str``: one unserializable value bound by a caller must not cost the batch.
        "payload": json.loads(
            json.dumps({k: v for k, v in line.items() if k not in _RESERVED}, default=str)
        ),
    }


class LogRepository(BaseRepository[LogLine]):
    """All ``log_lines`` SQL, bound to one session."""

    model: ClassVar[type[LogLine]] = LogLine

    async def append(
        self, lines: list[dict[str, Any]], *, instance: str = INSTANCE, lock_timeout_ms: int = 0
    ) -> None:
        """Append a batch as multi-row inserts; the caller commits.

        ``synchronous_commit = off`` for this transaction only: an unclean shutdown may lose the
        last milliseconds of lines, whose durable copy is on stdout. ``lock_timeout_ms`` bounds a
        wait on a lock held elsewhere (a TRUNCATE); ``0`` is Postgres's "no timeout".

        ``.values([...])``, not a parameter list: with no ``RETURNING``, SQLAlchemy would send a
        parameter list as one single-row statement per line.
        """
        if not lines:
            return
        await self.session.execute(sql_text("SET LOCAL synchronous_commit = off"))
        if lock_timeout_ms:
            await self.session.execute(sql_text(f"SET LOCAL lock_timeout = '{lock_timeout_ms}ms'"))
        rows = [_columns(line, instance) for line in lines]
        per_row = len(LogLine.__table__.columns)
        chunk_size = _MAX_STATEMENT_PARAMS // per_row
        for start in range(0, len(rows), chunk_size):
            await self.session.execute(insert(LogLine).values(rows[start : start + chunk_size]))

    async def roll(self, *, today: date, retention_days: int) -> int:
        """Create the day partitions ahead of ``today``, drop those past retention, and delete
        the expired rows left in the default partition; returns how many rows were deleted
        (dropped partitions not counted).

        Ahead, because a partition cannot be created once the default partition holds rows for
        its range: a missed day stays there for good, no longer droppable as a whole. The floor
        day is computed in ``roll_log_partitions`` only.
        """
        deleted = await self.session.scalar(
            # Unqualified: the search_path picks the schema, so a worktree or the test schema
            # rolls its own partitions.
            sql_text("SELECT roll_log_partitions(:today, :days)"),
            {"today": today, "days": retention_days},
        )
        return int(deleted or 0)

    async def purge(self, *, retention_days: int) -> int:
        """:meth:`roll` as of ``clock.now()``, not Postgres's ``current_date``."""
        return await self.roll(today=clock.now().date(), retention_days=retention_days)

    async def counted_by_payload_key(
        self,
        key: str,
        *,
        names: Collection[str],
        since: datetime,
        until: datetime,
        bucket: int,
    ) -> dict[tuple[str, datetime], int]:
        """Count the named lines per ``payload[key]`` value and per ``bucket``-second slot,
        grouped in Postgres (the Tasks screen counts per ``topic``)."""
        if not names:
            return {}
        # One expression object for select and group by: written twice it binds two parameters,
        # and Postgres no longer sees the same grouping.
        held = LogLine.payload[key].astext
        slot = func.to_timestamp(func.floor(extract("epoch", LogLine.ts) / bucket) * bucket)
        rows = await self.session.execute(
            select(held, slot, func.count())
            .where(LogLine.ts.between(since, until), LogLine.name.in_(list(names)))
            .group_by(held, slot)
        )
        return {(k, slot_at): int(n) for k, slot_at, n in rows if k}

    async def search(
        self,
        *,
        level: str | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
        request_id: str | None = None,
        text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        window: timedelta | None = DEFAULT_WINDOW,
        limit: int = 100,
    ) -> list[LogLine]:
        """Newest first, filters ANDed. An empty filter (``""`` from a query param) matches all.

        ``window`` bounds the read unless ``from_dt`` is given; ``None`` reads everything kept.
        """
        query = select(LogLine).order_by(LogLine.ts.desc()).limit(limit)
        floor = from_dt or (clock.now() - window if window else None)
        if floor:
            query = query.where(LogLine.ts >= floor)
        if to_dt:
            query = query.where(LogLine.ts <= to_dt)
        if level:
            query = query.where(LogLine.level == level.lower())
        if org_id:
            query = query.where(LogLine.org_id == org_id)
        if user_id:
            query = query.where(LogLine.user_id == user_id)
        if request_id:
            query = query.where(LogLine.request_id == request_id)
        if text:
            like = f"%{text}%"
            query = query.where(
                or_(
                    LogLine.name.ilike(like),
                    LogLine.logger.ilike(like),
                    cast(LogLine.payload, Text).ilike(like),
                    cast(LogLine.org_id, String).ilike(like),
                    cast(LogLine.user_id, String).ilike(like),
                    cast(LogLine.request_id, String).ilike(like),
                )
            )
        return list(await self.session.scalars(query))
