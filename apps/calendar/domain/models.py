import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field
from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.dto import Partial
from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class CalendarEvent(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "calendar_events"

    user_id: Mapped[uuid.UUID]
    title: Mapped[str] = mapped_column(String)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    location: Mapped[str] = mapped_column(String, default="")
    description: Mapped[str] = mapped_column(String, default="")


def format_event_time(starts_at: datetime, ends_at: datetime) -> str:
    """``1 July 2026, 14:00 – 15:00``, or both ends spelled out across days. Shown as is in the
    page and as ``when`` in JSON, so both drivers assert the same string.
    """

    def day(dt: datetime) -> str:
        return f"{dt.day} {dt:%B} {dt.year}"

    def hm(dt: datetime) -> str:
        return f"{dt:%H:%M}"

    if starts_at.date() == ends_at.date():
        return f"{day(starts_at)}, {hm(starts_at)} – {hm(ends_at)}"
    return f"{day(starts_at)}, {hm(starts_at)} – {day(ends_at)}, {hm(ends_at)}"


class CalendarEventCreate(BaseModel):
    """Times come whole (``start``, ``end``, JSON) or split into the form's date and time
    inputs. Blanks are refused by the handler, on the form."""

    title: str = ""
    start: str = ""
    end: str = ""
    start_date: str = ""
    start_time: str = ""
    end_date: str = ""
    end_time: str = ""
    location: str = ""
    description: str = ""


class CalendarEventPatch(Partial):
    """The editor sends the whole form, a JSON caller what changed."""

    title: str = ""
    start: str = ""
    end: str = ""
    start_date: str = ""
    start_time: str = ""
    end_date: str = ""
    end_time: str = ""
    location: str = ""
    description: str = ""


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
