import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.domain.models import ErrorEvent, ErrorGroup, IssueStatus
from apps.issues.domain.service import status_after_event
from apps.shared import clock

OPEN_STATUSES = (IssueStatus.new, IssueStatus.unresolved, IssueStatus.regressed)


@dataclass(frozen=True)
class RecordedEvent:
    group: ErrorGroup
    opened: bool  # first event ever for this fingerprint
    regressed: bool  # this event flipped a resolved group back open


async def record_event(
    session: AsyncSession,
    *,
    fingerprint: str,
    title: str,
    version: str,
    context: dict[str, Any],
) -> RecordedEvent:
    """Fold one occurrence into its group (creating it) and append the event row."""
    now = clock.now()
    opened = regressed = False
    group = await session.scalar(select(ErrorGroup).where(ErrorGroup.fingerprint == fingerprint))
    if group is None:
        group = ErrorGroup(
            fingerprint=fingerprint,
            title=title,
            status=IssueStatus.new,
            count=0,
            first_seen=now,
            last_seen=now,
            first_version=version,
            last_version=version,
        )
        session.add(group)
        opened = True
    else:
        next_status = status_after_event(
            IssueStatus(group.status), group.resolved_in_version, version
        )
        regressed = next_status is IssueStatus.regressed and group.status != next_status
        group.status = next_status
    group.count += 1
    group.last_seen = now
    group.last_version = version
    await session.flush()
    session.add(ErrorEvent(group_id=group.id, created_at=now, context=context))
    await session.flush()
    return RecordedEvent(group=group, opened=opened, regressed=regressed)


class ErrorGroupRepository:
    """Console-side reads and triage — driven by the BYPASSRLS admin session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_groups(self, status: str = "", limit: int = 100) -> list[ErrorGroup]:
        query = select(ErrorGroup).order_by(ErrorGroup.last_seen.desc()).limit(limit)
        if status:
            query = query.where(ErrorGroup.status == status)
        return list(await self.session.scalars(query))

    async def get(self, group_id: uuid.UUID) -> ErrorGroup | None:
        return await self.session.get(ErrorGroup, group_id)

    async def set_status(self, group: ErrorGroup, status: IssueStatus, version: str) -> None:
        group.status = status
        group.resolved_in_version = version if status is IssueStatus.resolved else None
        await self.session.flush()

    async def events(
        self, group_id: uuid.UUID, before_id: uuid.UUID | None = None, limit: int = 20
    ) -> tuple[list[ErrorEvent], uuid.UUID | None]:
        """Newest-first cursor page of a group's events (log-viewer pattern)."""
        query = (
            select(ErrorEvent)
            .where(ErrorEvent.group_id == group_id)
            .order_by(ErrorEvent.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            query = query.where(ErrorEvent.id < before_id)
        rows = list(await self.session.scalars(query))
        next_before_id = rows[limit - 1].id if len(rows) > limit else None
        return rows[:limit], next_before_id

    async def daily_counts(self, group_id: uuid.UUID, *, days: int) -> dict[str, int]:
        """Occurrences per ISO day over the trailing window — the detail sparkline."""
        since = clock.now() - timedelta(days=days - 1)
        day = func.date(ErrorEvent.created_at)
        rows = await self.session.execute(
            select(day, func.count())
            .where(ErrorEvent.group_id == group_id, ErrorEvent.created_at >= since)
            .group_by(day)
        )
        return {d.isoformat(): n for d, n in rows.all()}

    async def unresolved_count(self) -> int:
        return (
            await self.session.scalar(
                select(func.count())
                .select_from(ErrorGroup)
                .where(ErrorGroup.status.in_([s.value for s in OPEN_STATUSES]))
            )
            or 0
        )


async def purge_old_events(session: AsyncSession, retention_days: int) -> int:
    """Retention consumer: drop event rows past the window; groups keep their totals."""
    deleted = await session.scalar(
        text(
            "WITH purged AS ("
            "  DELETE FROM error_events"
            "  WHERE created_at < now() - make_interval(days => :days) RETURNING 1"
            ") SELECT count(*) FROM purged"
        ),
        {"days": retention_days},
    )
    return int(deleted or 0)
