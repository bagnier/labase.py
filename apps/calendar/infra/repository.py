import uuid
from datetime import datetime

from sqlalchemy import select

from apps.calendar.domain.models import CalendarEvent
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository


class CalendarEventRepository(OrgScopedRepository[CalendarEvent]):
    model = CalendarEvent
    default_order = CalendarEvent.starts_at.asc()

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
