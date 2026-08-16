"""Calendar's business events — an event's lifecycle on the shared trail.

Plain CRUD: ``kind`` derives to ``"calendar.created"`` / ``"calendar.updated"`` /
``"calendar.deleted"`` from the shared abstracts; the router emits them on the request's session,
scoped by ``user_id``/``org_id``.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped


class CalendarEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[str] = "calendar"
    icon: ClassVar[str] = "calendar-dots"


@dataclass(frozen=True, kw_only=True)
class CalendarCreated(CalendarEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class CalendarUpdated(CalendarEvent, EntityUpdated):
    pass


@dataclass(frozen=True, kw_only=True)
class CalendarDeleted(CalendarEvent, EntityDeleted):
    pass
