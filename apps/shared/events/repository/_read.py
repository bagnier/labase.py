"""Read path — RLS-scoped reads of the trail for the observability timeline and dashboards."""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import Date, Text, cast, func, or_, select

from apps.shared import clock
from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository._base import _EventSQL


class _ReadsEvents(_EventSQL):
    async def search(
        self,
        *,
        level: str | None = None,
        org_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        entity_id: str | None = None,
        request_id: str | None = None,
        app: str | None = None,
        text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BusinessEventLog]:
        """Newest-first read under the filters. RLS already scopes rows to the reader (self + orgs);
        the ``user_id``/``org_id`` filters narrow to one feed on top of that. ``app`` matches the
        ``kind`` prefix (``todo`` → ``todo.*``)."""
        query = (
            select(BusinessEventLog)
            .order_by(BusinessEventLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if level:
            query = query.where(BusinessEventLog.level == level)
        if org_id:
            query = query.where(BusinessEventLog.org_id == org_id)
        if user_id:
            query = query.where(BusinessEventLog.user_id == user_id)
        if entity_id:
            query = query.where(BusinessEventLog.entity_id == entity_id)
        if request_id:
            query = query.where(BusinessEventLog.request_id == request_id)
        if app:
            query = query.where(BusinessEventLog.kind.like(f"{app}.%"))
        if text:
            like = f"%{text}%"
            query = query.where(
                or_(
                    BusinessEventLog.kind.ilike(like),
                    cast(BusinessEventLog.payload, Text).ilike(like),
                )
            )
        if from_dt:
            query = query.where(BusinessEventLog.created_at >= from_dt)
        if to_dt:
            query = query.where(BusinessEventLog.created_at <= to_dt)
        return list(await self.session.scalars(query))

    async def daily_counts(
        self,
        *,
        user_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        days: int = 366,
    ) -> dict[date, int]:
        """Per-day counts for the contribution calendar. Missing days don't appear — the calendar
        builder fills the gaps. RLS-scoped like :meth:`search`."""
        since = clock.now() - timedelta(days=days)
        day = cast(BusinessEventLog.created_at, Date)
        query = select(day, func.count()).where(BusinessEventLog.created_at >= since).group_by(day)
        if user_id:
            query = query.where(BusinessEventLog.user_id == user_id)
        if org_id:
            query = query.where(BusinessEventLog.org_id == org_id)
        rows = await self.session.execute(query)
        return {d: n for d, n in rows.all()}
