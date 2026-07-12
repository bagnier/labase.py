"""Read-only inter-app surface: issue occurrences flattened for the unified logs timeline.

``apps/logs`` merges these with the business-events trail and the firehose; it must not reach
into the issues tables directly (they're private to this context), so it calls this contract query.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Text, cast, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.domain.models import ErrorEvent, ErrorGroup


@dataclass(frozen=True)
class IssueEventRow:
    ts: datetime
    title: str
    context: dict[str, Any]


async def search_issue_events(
    session: AsyncSession,
    *,
    org_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
) -> list[IssueEventRow]:
    """Newest-first, bounded read of error occurrences. Org/user/request are matched inside the
    JSONB ``context`` (issues has no dedicated columns); the group supplies the title."""
    query = (
        select(ErrorEvent, ErrorGroup.title)
        .join(ErrorGroup, ErrorGroup.id == ErrorEvent.group_id)
        .order_by(ErrorEvent.id.desc())
        .limit(limit)
    )
    if org_id:
        query = query.where(ErrorEvent.context["org_id"].astext == org_id)
    if user_id:
        query = query.where(ErrorEvent.context["user_id"].astext == user_id)
    if request_id:
        query = query.where(ErrorEvent.context["request_id"].astext == request_id)
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(ErrorGroup.title.ilike(like), cast(ErrorEvent.context, Text).ilike(like))
        )
    if from_dt:
        query = query.where(ErrorEvent.created_at >= from_dt)
    if to_dt:
        query = query.where(ErrorEvent.created_at <= to_dt)
    rows = await session.execute(query)
    return [
        IssueEventRow(ts=event.created_at, title=title, context=event.context or {})
        for event, title in rows.all()
    ]
