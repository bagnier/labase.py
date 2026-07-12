"""Calendar's business events — an event's lifecycle on the shared trail.

Plain CRUD: ``kind`` derives to ``"calendar.created"`` / ``"calendar.updated"`` /
``"calendar.deleted"`` from the shared abstracts; the persister on the
:class:`~apps.shared.events.BusinessEvent` base records them, scoped by ``actor_id``/``org_id``.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated


class CalendarEvent(BusinessEvent):
    entity: ClassVar[str] = "calendar"
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
