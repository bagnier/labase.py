import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.domain.models import Issue, IssueStatus, Occurrence
from apps.issues.domain.service import status_after_occurrence
from apps.shared import clock
from apps.shared.persistence.repository import count_where

OPEN_STATUSES = (IssueStatus.new, IssueStatus.unresolved, IssueStatus.regressed)


@dataclass(frozen=True)
class SeenOccurrence:
    issue: Issue
    opened: bool  # the first occurrence ever for this fingerprint
    regressed: bool  # this occurrence flipped a resolved issue back open


async def see_occurrence(
    session: AsyncSession,
    *,
    fingerprint: str,
    title: str,
    version: str,
    context: dict[str, Any],
) -> SeenOccurrence:
    """Fold one occurrence into its issue (creating it) and append the occurrence."""
    now = clock.now()
    opened = regressed = False
    issue = await session.scalar(select(Issue).where(Issue.fingerprint == fingerprint))
    if issue is None:
        issue = Issue(
            fingerprint=fingerprint,
            title=title,
            status=IssueStatus.new,
            occurrence_count=0,
            first_seen=now,
            last_seen=now,
            first_release=version,
            last_release=version,
        )
        session.add(issue)
        opened = True
    else:
        next_status = status_after_occurrence(
            IssueStatus(issue.status), issue.resolved_in_release, version
        )
        regressed = next_status is IssueStatus.regressed and issue.status != next_status
        issue.status = next_status
    issue.occurrence_count += 1
    issue.last_seen = now
    issue.last_release = version
    await session.flush()
    session.add(Occurrence(issue_id=issue.id, created_at=now, context=context))
    await session.flush()
    return SeenOccurrence(issue=issue, opened=opened, regressed=regressed)


class IssueRepository:
    """Console-side reads and triage — driven by the BYPASSRLS admin session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_issues(self, status: IssueStatus | None = None, limit: int = 100) -> list[Issue]:
        query = select(Issue).order_by(Issue.last_seen.desc()).limit(limit)
        if status is not None:
            query = query.where(Issue.status == status)
        return list(await self.session.scalars(query))

    async def get(self, issue_id: uuid.UUID) -> Issue | None:
        return await self.session.get(Issue, issue_id)

    async def set_status(self, issue: Issue, status: IssueStatus, version: str) -> None:
        issue.status = status
        issue.resolved_in_release = version if status is IssueStatus.resolved else None
        await self.session.flush()

    async def occurrences(
        self, issue_id: uuid.UUID, before_id: uuid.UUID | None = None, limit: int = 20
    ) -> tuple[list[Occurrence], uuid.UUID | None]:
        """Newest-first cursor page of an issue's occurrences (log-viewer pattern)."""
        query = (
            select(Occurrence)
            .where(Occurrence.issue_id == issue_id)
            .order_by(Occurrence.id.desc())
            .limit(limit + 1)
        )
        if before_id is not None:
            query = query.where(Occurrence.id < before_id)
        found = list(await self.session.scalars(query))
        next_before_id = found[limit - 1].id if len(found) > limit else None
        return found[:limit], next_before_id

    async def daily_counts(self, issue_id: uuid.UUID, *, days: int) -> dict[str, int]:
        """Occurrences per ISO day over the trailing window — the detail sparkline."""
        since = clock.now() - timedelta(days=days - 1)
        day = func.date(Occurrence.created_at)
        per_day = await self.session.execute(
            select(day, func.count())
            .where(Occurrence.issue_id == issue_id, Occurrence.created_at >= since)
            .group_by(day)
        )
        return {d.isoformat(): n for d, n in per_day.all()}

    async def unresolved_count(self) -> int:
        return await count_where(
            self.session, Issue, Issue.status.in_([s.value for s in OPEN_STATUSES])
        )


async def purge_old_occurrences(session: AsyncSession, retention_days: int) -> int:
    """Retention consumer: drop occurrences past the window; issues keep their totals."""
    deleted = await session.scalar(
        text(
            "WITH purged AS ("
            "  DELETE FROM issue_occurrences"
            "  WHERE created_at < now() - make_interval(days => :days) RETURNING 1"
            ") SELECT count(*) FROM purged"
        ),
        {"days": retention_days},
    )
    return int(deleted or 0)
