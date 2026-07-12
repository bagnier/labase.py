"""To-do's business events — a task's life recorded on the shared trail.

The verbs are the *domain* actions, not flat CRUD: a task is created, **edited** (its title),
**ticked**/un-ticked (its done flag) and deleted. Edit/tick/untick are all forms of *update*, so
they derive from :class:`~apps.shared.events.EntityUpdated` (sharing its ``entity_id``/``label``
shape) but override ``verb`` — giving each a distinct ``kind`` (``"todo.ticked"`` …) so the
profile/dashboard timeline reads "Ticked", not a flat "Updated". ``kind`` is derived from
``entity`` + ``verb``; the persister on the ``BusinessEvent`` base records them.
"""

from dataclasses import dataclass
from typing import ClassVar

from apps.shared.events import BusinessEvent, EntityCreated, EntityDeleted, EntityUpdated


class TodoEvent(BusinessEvent):
    """Per-app mixin: fixes the entity prefix and the icon every to-do event carries."""

    entity: ClassVar[str] = "todo"
    icon: ClassVar[str] = "clipboard-text"


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
