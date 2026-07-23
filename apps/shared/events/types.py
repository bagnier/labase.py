"""Business events — the typed vocabulary of "something happened".

A business event is a frozen dataclass emitted on the bus (type-dispatched to subscribers)
*and* persisted to the ``business_events`` store by the bus persister. It declares only who
acted (``actor_id``) and which org it concerns (``org_id``); the persister enriches
``ip``/``request_id``/``level`` from the request contextvars at write time.

Most mutations are CRUD, so the ``EntityCreated``/``EntityUpdated``/``EntityDeleted`` abstracts
derive the event ``kind`` (``"<app>.<verb>"``, e.g. ``"todo.created"``) from a one-line per-app
mixin — no ``kind`` string is hand-written::

    class TodoEvent(BusinessEvent):
        entity = "todo"

    @dataclass(frozen=True, kw_only=True)
    class TodoCreated(TodoEvent, EntityCreated):
        title: str

Non-CRUD actions (sign-in, a member joining, a page being published) subclass
:class:`BusinessEvent` directly and set an explicit ``kind``.
"""

from dataclasses import dataclass, fields
from typing import Any, ClassVar


@dataclass(frozen=True, kw_only=True)
class BusinessEvent:
    """Base for every recorded domain event. ``kw_only`` so subclasses may add required payload
    fields without tripping dataclass default-ordering against the base's optional scoping."""

    actor_id: str | None = None
    org_id: str | None = None
    entity_id: str | None = None  # the concerned entity's id (todo pk, page slug…), for correlation

    # Class-level identity/metadata — never instance fields, so they stay out of the payload.
    kind: ClassVar[str] = ""  # dotted "<app>.<subject>"; derived for CRUD, explicit otherwise
    level: ClassVar[str] = "info"  # security/failure events set "warning"
    icon: ClassVar[str] = "circle"  # phosphor name the event OWNS, so shared never maps apps→icons
    entity: ClassVar[str] = ""  # the app prefix, set by a per-app mixin for CRUD events

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # A concrete CRUD event has both an entity (from its app mixin) and a verb (from the
        # CRUD abstract): derive its kind once. Explicit `kind = "..."` on the class wins.
        entity = getattr(cls, "entity", "")
        verb = getattr(cls, "verb", "")
        if entity and verb and "kind" not in cls.__dict__:
            cls.kind = f"{entity}.{verb}"
        # A concrete event (non-empty kind) registers itself so the tailer can reconstruct it from
        # a stored row. Abstract bases (EntityCreated…, kind still "") never do.
        if cls.kind:
            _event_classes[cls.kind] = cls


@dataclass(frozen=True, kw_only=True)
class EntityCreated(BusinessEvent):
    """An org-scoped entity was created — ``kind`` becomes ``"<entity>.created"``. The created
    row's id rides on the base's ``entity_id``; ``label`` is its display name."""

    verb: ClassVar[str] = "created"
    label: str | None = None


@dataclass(frozen=True, kw_only=True)
class EntityUpdated(BusinessEvent):
    """An org-scoped entity was updated — ``kind`` becomes ``"<entity>.updated"``."""

    verb: ClassVar[str] = "updated"
    label: str | None = None


@dataclass(frozen=True, kw_only=True)
class EntityDeleted(BusinessEvent):
    """An org-scoped entity was deleted — ``kind`` becomes ``"<entity>.deleted"``."""

    verb: ClassVar[str] = "deleted"
    label: str | None = None


# Concrete BusinessEvent classes keyed by their dotted ``kind`` — populated by __init_subclass__ as
# each app's events are imported. Lets the event tailer rebuild a typed event from a persisted
# ``business_events`` row, which carries only the kind string.
_event_classes: dict[str, type[BusinessEvent]] = {}


def event_class_for(kind: str) -> type[BusinessEvent] | None:
    """The concrete ``BusinessEvent`` subclass for a dotted ``kind``, or ``None`` if unknown."""
    return _event_classes.get(kind)


def reconstruct(event_type: type[BusinessEvent], payload: dict[str, Any]) -> BusinessEvent:
    """Rebuild a frozen event from a stored payload/row, keeping only keys that are event fields.

    Both delivery paths off the trail reconstruct the typed event this way: transport-only keys
    (the row id ``event_id``, the denormalized ``actor`` handle) are simply dropped."""
    names = {f.name for f in fields(event_type)}
    return event_type(**{k: v for k, v in payload.items() if k in names})
