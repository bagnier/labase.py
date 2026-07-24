"""Business events — the typed vocabulary of "something happened".

A business event is a frozen dataclass persisted to the ``business_events`` trail by the bus's
``emit`` — no handler runs at emit; the listener dispatches by type off the trail after commit. It
declares only who acted (``actor_id``) and which org it concerns (``org_id``); the write path
enriches ``ip``/``request_id`` from the request contextvars at write time, while
``kind``/``level``/``icon`` are the event's own class metadata.

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

import contextlib
import typing
import uuid
from dataclasses import dataclass, fields
from functools import cache
from typing import Any, ClassVar, Self

from apps.shared.events.registry import registry


def _wants_uuid(hint: Any) -> bool:
    """A field is a uuid carrier if its annotation is ``uuid.UUID`` or a union that includes it
    (``uuid.UUID | None``, or the polymorphic ``uuid.UUID | str | None``)."""
    return hint is uuid.UUID or uuid.UUID in typing.get_args(hint)


@cache
def _uuid_fields(cls: type) -> frozenset[str]:
    """The dataclass fields whose type carries a ``uuid.UUID`` — resolved once per class. Drives the
    generic re-parse so any DTO can carry uuids without a hand-maintained field list."""
    hints = typing.get_type_hints(cls)
    return frozenset(f.name for f in fields(cls) if _wants_uuid(hints.get(f.name)))


@dataclass(frozen=True, kw_only=True)
class BusinessEvent:
    """Base for every recorded domain event. ``kw_only`` so subclasses may add required payload
    fields without tripping dataclass default-ordering against the base's optional scoping."""

    actor_id: uuid.UUID | None = None
    org_id: uuid.UUID | None = None
    # the concerned entity's id, for correlation — polymorphic: a uuid pk, a page slug, or an int.
    entity_id: uuid.UUID | str | None = None

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
        # A concrete event (non-empty kind) registers itself in the catalog so the listener can
        # reconstruct it from a stored row. Abstract bases (EntityCreated…, kind still "") never do.
        if cls.kind:
            registry.register_event(cls)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Rebuild the event from a stored row — dropping transport-only keys (``event_id``, the
        denormalized ``actor`` handle) that aren't event fields, and re-parsing every uuid-typed
        field the task queue serialized to a string. The re-parse is generic (driven by the field
        annotations) and defensive: a value that isn't a valid uuid — a page slug in the polymorphic
        ``entity_id``, a redacted ``"***"`` token — is left as-is rather than crashing the rebuild.
        Both delivery paths use this."""
        names = {f.name for f in fields(cls)}
        kept = {k: v for k, v in payload.items() if k in names}
        for key in _uuid_fields(cls):
            if isinstance(kept.get(key), str):
                with contextlib.suppress(ValueError):
                    kept[key] = uuid.UUID(kept[key])
        return cls(**kept)


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
