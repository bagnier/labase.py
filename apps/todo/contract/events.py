"""To-do facts, named by domain action (created, edited, ticked, unticked, deleted), so a feed
reads "Ticked" rather than "Updated".
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated, OrgScoped
from apps.shared.vocabulary import AppName, PhosphorIcon


class TodoEvent(OrgScoped, BusinessEvent):
    app_name: ClassVar[AppName] = "todo"
    icon: ClassVar[PhosphorIcon] = "clipboard-text"


@dataclass(frozen=True, kw_only=True)
class TodoCreated(TodoEvent, EntityCreated):
    pass


@dataclass(frozen=True, kw_only=True)
class TodoDeleted(TodoEvent, EntityDeleted):
    pass


@dataclass(frozen=True, kw_only=True)
class TodoEdited(TodoEvent, EntityUpdated):
    verb: ClassVar[str] = "edited"


@dataclass(frozen=True, kw_only=True)
class TodoTicked(TodoEvent, EntityUpdated):
    verb: ClassVar[str] = "ticked"


@dataclass(frozen=True, kw_only=True)
class TodoUnticked(TodoEvent, EntityUpdated):
    verb: ClassVar[str] = "unticked"
