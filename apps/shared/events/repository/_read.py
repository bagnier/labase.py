"""Read path — RLS-scoped reads of the trail for the observability timeline and dashboards."""

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import Date, Text, cast, func, or_, select

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository._base import _EventSQL


class _ReadsEvents(_EventSQL):
    async def search(
        self,
        *,
        org_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        request_id: uuid.UUID | None = None,
        app: str | None = None,
        text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BusinessEventRecord]:
        """Newest-first read under the filters. RLS already scopes rows to the reader (self + orgs);
        the ``user_id``/``org_id`` filters narrow to one feed on top of that. ``app`` matches the
        row's own ``app_name`` column — an equality, not a scan of the composed kind's prefix."""
        query = (
            select(BusinessEventRecord)
            .order_by(BusinessEventRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if org_id:
            query = query.where(BusinessEventRecord.org_id == org_id)
        if user_id:
            query = query.where(BusinessEventRecord.user_id == user_id)
        if entity_id:
            query = query.where(BusinessEventRecord.entity_id == entity_id)
        if request_id:
            query = query.where(BusinessEventRecord.request_id == request_id)
        if app:
            query = query.where(BusinessEventRecord.app_name == app)
        if text:
            like = f"%{text}%"
            query = query.where(
                or_(
                    BusinessEventRecord.kind.ilike(like),
                    cast(BusinessEventRecord.payload, Text).ilike(like),
                )
            )
        if from_dt:
            query = query.where(BusinessEventRecord.created_at >= from_dt)
        if to_dt:
            query = query.where(BusinessEventRecord.created_at <= to_dt)
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
        day = cast(BusinessEventRecord.created_at, Date)
        query = (
            select(day, func.count())
            .where(BusinessEventRecord.created_at >= since)
            .group_by(day)
        )
        if user_id:
            query = query.where(BusinessEventRecord.user_id == user_id)
        if org_id:
            query = query.where(BusinessEventRecord.org_id == org_id)
        rows = await self.session.execute(query)
        return {d: n for d, n in rows.all()}
