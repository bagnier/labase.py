import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.calendar.domain.models import CalendarEvent
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository


class CalendarEventRepository(OrgScopedRepository[CalendarEvent]):
    model = CalendarEvent

    async def all(self) -> list[CalendarEvent]:
        return list(
            await self.session.scalars(
                select(CalendarEvent)
                .where(CalendarEvent.org_id == self.org_id)
                .order_by(CalendarEvent.starts_at)
            )
        )

    async def upcoming(self) -> list[CalendarEvent]:
        """Events that have not started yet, soonest first — drives the dashboard overview."""
        return list(
            await self.session.scalars(
                select(CalendarEvent)
                .where(
                    CalendarEvent.org_id == self.org_id,
                    CalendarEvent.starts_at >= clock.now(),
                )
                .order_by(CalendarEvent.starts_at)
            )
        )

    async def add(
        self,
        user_id: uuid.UUID,
        title: str,
        starts_at: datetime,
        ends_at: datetime,
        location: str = "",
        description: str = "",
    ) -> CalendarEvent:
        event = CalendarEvent(
            org_id=self.org_id,
            user_id=user_id,
            title=title,
            starts_at=starts_at,
            ends_at=ends_at,
            location=location,
            description=description,
        )
        self.session.add(event)
        await self.session.flush()
        return event


async def count_all(session: AsyncSession) -> int:
    """Server-wide event count, across every organisation (console overview)."""
    return int(await session.scalar(select(func.count()).select_from(CalendarEvent)) or 0)
