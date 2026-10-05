"""Calendar facts, plain CRUD: ``calendar.created``, ``.updated``, ``.deleted``."""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class CalendarEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "calendar"
    icon: ClassVar[PhosphorIcon] = "calendar-dots"


@dataclass(frozen=True, kw_only=True)
class CalendarCreated(CalendarEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class CalendarUpdated(CalendarEvent, EntityUpdated):
    pass


@dataclass(frozen=True, kw_only=True)
class CalendarDeleted(CalendarEvent, EntityDeleted):
    pass
