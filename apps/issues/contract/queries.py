"""Read-only inter-app surface: issue occurrences flattened for the unified logs timeline.

``apps/timeline`` merges these with the business-events journal and the log sink; it must not reach
into the issues tables directly (they're private to this context), so it calls this contract query.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.domain.models import Issue, Occurrence


@dataclass(frozen=True)
class IssueOccurrence:
    """One sighting, flattened for the timeline — with the issue it belongs to.

    ``issue_id`` is what makes the timeline row a link: the row names the exception, while the
    stack, the triage state and the other occurrences live on the issue's own screen. Without it
    a reader had to go find that issue again by its title."""

    ts: datetime
    title: str
    context: dict[str, Any]
    issue_id: uuid.UUID


async def search_issue_occurrences(
    session: AsyncSession,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
) -> list[IssueOccurrence]:
    """Newest-first, bounded read of issue occurrences. Org/user/request are matched inside the
    JSONB ``context`` (issues has no dedicated columns); the issue supplies the title."""
    query = (
        select(Occurrence, Issue.title, Issue.id)
        .join(Issue, Issue.id == Occurrence.issue_id)
        .order_by(Occurrence.id.desc())
        .limit(limit)
    )
    if org_id:
        query = query.where(Occurrence.context["org_id"].astext == org_id)
    if user_id:
        query = query.where(Occurrence.context["user_id"].astext == user_id)
    if request_id:
        query = query.where(Occurrence.context["request_id"].astext == request_id)
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(Issue.title.ilike(like), cast(Occurrence.context, Text).ilike(like))
        )
    if from_dt:
        query = query.where(Occurrence.created_at >= from_dt)
    if to_dt:
        query = query.where(Occurrence.created_at <= to_dt)
    rows = await session.execute(query)
    return [
        IssueOccurrence(
            ts=occurrence.created_at,
            title=title,
            context=occurrence.context or {},
            issue_id=issue_id,
        )
        for occurrence, title, issue_id in rows.all()
    ]
