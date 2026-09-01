"""The log repository — the one owner of ``log_lines``.

:class:`LogRepository` is :class:`~apps.shared.persistence.repository.BaseRepository` over
:class:`~apps.shared.logs.models.LogLine`, and holds every query against the table
in one place: the batch append the sink's drain performs, the filtered read the console Timeline
merges with its two other sources, and the retention purge.

The mirror of :mod:`apps.shared.events.repository` for the technical side. How a line *gets* here
— the queue, the structlog processor, the background drain, the file fallback — is the sink's
business, not this module's.
"""

import json
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from sqlalchemy import String, Text, cast, insert, or_, select
from sqlalchemy import text as sql_text  # aliased: ``search`` takes a ``text`` filter of its own

from apps.shared import clock
from apps.shared.logs.models import LogLine
from apps.shared.persistence.repository import BaseRepository

# How far back the Timeline reads by default. Not retention — the table keeps whatever the purge
# leaves — just the bound on an otherwise unfiltered screen. An explicit ``from_dt`` reaches past
# it, which the two-day file window this replaced could not honour.
DEFAULT_WINDOW = timedelta(days=2)

# This process, for the ``instance`` column. One table, N writers: a line that cannot say where it
# came from makes an outage on one instance look like an outage everywhere.
INSTANCE = uuid.uuid4().hex[:8]

# Event-dict keys promoted to first-class columns; everything else lands in ``payload``.
_RESERVED = {"timestamp", "level", "logger", "event", "org_id", "user_id", "request_id"}


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, str):
        ts = datetime.fromisoformat(value)
    else:
        ts = clock.now()
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _as_text(value: Any) -> str | None:
    """A correlation key as the column holds it. The context may carry a uuid, a str, or something
    a test bound by hand; the column is text precisely so none of those is a reason to drop a
    line."""
    return None if value is None else str(value)


def _columns(line: dict[str, Any], instance: str) -> dict[str, Any]:
    """One queued event dict, flattened to the row's columns."""
    return {
        "ts": _parse_ts(line.get("timestamp")),
        "level": str(line.get("level") or "info"),
        "logger": str(line.get("logger") or ""),
        # ``event`` is structlog's own key for the trace name — the library's word on the wire,
        # never ours in the column that stores it.
        "name": str(line.get("event") or ""),
        "org_id": _as_text(line.get("org_id")),
        "user_id": _as_text(line.get("user_id")),
        "request_id": _as_text(line.get("request_id")),
        "instance": instance,
        # ``default=str``, the same tolerance the day-file fallback has: the context carries
        # whatever a caller bound — a UUID, an exception — and one such value must not cost the
        # store the whole batch it rides in.
        "payload": json.loads(
            json.dumps({k: v for k, v in line.items() if k not in _RESERVED}, default=str)
        ),
    }


class LogRepository(BaseRepository[LogLine]):
    """All ``log_lines`` SQL, bound to one session — the twin of ``EventRepository`` for the
    technical side.

    Append, search, purge: the three things a log store owes. Nothing about *how* lines get here,
    which is the sink's business (:mod:`apps.shared.logs.sink`).
    """

    model: ClassVar[type[LogLine]] = LogLine

    async def append(self, lines: list[dict[str, Any]], *, instance: str = INSTANCE) -> None:
        """Append a batch of queued lines; the caller commits.

        One ``execute`` for the whole batch: a burst costs one round trip, not one per line — the
        same reason the file fallback opens its day file once per drain.

        ``synchronous_commit`` is off for this transaction: the commit returns without waiting
        for the WAL to reach disk, which is the single cheapest thing that makes a log table keep
        up with a busy server. What it costs is the last few milliseconds of lines on an unclean
        shutdown — already the doctrine here (the queue is bounded and drops, the drain is
        best-effort, stdout carries the durable copy). ``LOCAL``, so it dies with the transaction
        and never leaks onto a caller that meant to be durable.

        Nothing here has to silence itself any more: with no per-statement line, this INSERT
        writes nothing that the next drain would insert and log again.
        """
        if not lines:
            return
        await self.session.execute(sql_text("SET LOCAL synchronous_commit = off"))
        await self.session.execute(insert(LogLine), [_columns(line, instance) for line in lines])

    async def roll(self, *, today: date, retention_days: int) -> int:
        """Create the day partitions just ahead of ``today`` and drop those past retention;
        returns how many were dropped.

        Working *ahead* is the correctness condition, not an optimisation: a partition cannot be
        created for a range the default partition already holds rows for, so a day the roll misses
        belongs to the default partition for good — readable, but no longer droppable as a unit.
        """
        dropped = await self.session.scalar(
            # Unqualified, like the journal's ``record_business_event``: the search_path picks the
            # schema, which is what makes a worktree or the test schema manage its own partitions
            # rather than reach into ``public``.
            sql_text("SELECT roll_log_partitions(:today, :days)"),
            {"today": today, "days": retention_days},
        )
        return int(dropped or 0)

    async def purge(self, *, retention_days: int) -> int:
        """Drop lines past the retention window; returns how many. The delete the day files
        promised ("retention is a plain file delete") and never performed.

        Two moves, because the table is partitioned by day and a day can end up in either place:

        1. **Roll the partitions.** Yesterday's whole day is dropped as a unit — instant, and it
           leaves no dead tuples for VACUUM, which is the point of partitioning a table that takes
           one row per log line. The same call creates the days ahead, before an insert needs one.
        2. **Delete the stragglers.** Anything past the floor still in the default partition — a
           line dated outside every range, or a day the roll fell behind on. Cheap, because the
           bulk left with the dropped partitions.

        Counted through a CTE rather than off ``rowcount``, the shape ``purge_old_occurrences``
        and the rate limiter's purge already use: one statement either way, and the count comes
        back as a plain scalar instead of a cursor attribute the type checker cannot see.

        Both halves take their date from ``clock.now()``, never from Postgres' ``current_date``:
        one clock, here as everywhere, which is also what lets a test pin it.
        """
        now = clock.now()
        await self.roll(today=now.date(), retention_days=retention_days)
        deleted = await self.session.scalar(
            sql_text(
                "WITH purged AS ("
                "  DELETE FROM log_lines WHERE ts < :floor RETURNING 1"
                ") SELECT count(*) FROM purged"
            ),
            {"floor": now - timedelta(days=retention_days)},
        )
        return int(deleted or 0)

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
        """Newest-first read under the given filters.

        ``window`` bounds an otherwise unfiltered read; an explicit ``from_dt`` replaces it
        rather than tightening it, because the sink — unlike the two-day file window it replaced —
        actually holds what is being asked for. ``window=None`` reads all the purge has left.

        Filters combine with AND, and an unset one matches everything — empty, not just ``None``,
        because these arrive from URL query params where an untouched field is ``""``.
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
            # The whole record, payload included — what the file reader's substring scan covered.
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
