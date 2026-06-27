import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared import clock
from apps.shared.persistence.base import Base


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(String, default="")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )

    __mapper_args__ = {"version_id_col": version}


def format_event_time(starts_at: datetime, ends_at: datetime) -> str:
    """Human-readable event time — the single source for the cross-driver display string.

    Same-day events read ``1 July 2026, 14:00 – 15:00``; multi-day events spell out both ends.
    Rendered verbatim in the HTML detail view and exposed as the ``when`` field on
    :class:`CalendarEventRead`, so the browser and API drivers assert the very same literal.
    """

    def day(dt: datetime) -> str:
        return f"{dt.day} {dt:%B} {dt.year}"

    def hm(dt: datetime) -> str:
        return f"{dt:%H:%M}"

    if starts_at.date() == ends_at.date():
        return f"{day(starts_at)}, {hm(starts_at)} – {hm(ends_at)}"
    return f"{day(starts_at)}, {hm(starts_at)} – {day(ends_at)}, {hm(ends_at)}"


class CalendarEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    starts_at: datetime
    ends_at: datetime
    location: str
    description: str

    @computed_field
    @property
    def when(self) -> str:
        return format_event_time(self.starts_at, self.ends_at)
