"""Business events: the typed vocabulary of "something happened".

An event declares who acted (``user_id``) and, through :class:`OrgScoped`, which org it concerns;
the journal writer adds ``ip_address`` and ``request_id`` from the request context. ``kind`` is
always ``"<app_name>.<verb>"``, never hand-written. CRUD facts take their verb from the
``Entity*`` bases, other facts set ``verb`` themselves::

    class TodoEvent(OrgScoped, BusinessEvent):
        app_name = "todo"

    @dataclass(frozen=True, kw_only=True)
    class TodoCreated(TodoEvent, EntityCreated):
        title: str
"""

import contextlib
import typing
import uuid
from collections.abc import Callable
from dataclasses import MISSING, dataclass, fields
from datetime import datetime
from functools import cache
from typing import Any, ClassVar, Self

from apps.shared.events.catalog import catalog
from apps.shared.vocabulary import AppName, PhosphorIcon

# How to parse back a field that ``event_to_record`` wrote as a string for the queue's JSON.
_REPARSERS: dict[type, Callable[[str], Any]] = {
    uuid.UUID: uuid.UUID,
    datetime: datetime.fromisoformat,
}


@cache
def _fields_carrying(cls: type[BusinessEvent], target: type) -> frozenset[str]:
    """The fields annotated ``target`` or a union including it (``uuid.UUID | None``)."""
    hints = typing.get_type_hints(cls)
    return frozenset(
        f.name
        for f in fields(cls)
        if (hint := hints.get(f.name)) is target or target in typing.get_args(hint)
    )


# Matched against the field name without underscores: ``api_key`` hits ``apikey``.
_SECRET_FRAGMENTS = (
    "token",
    "password",
    "passphrase",
    "passcode",
    "secret",
    "credential",
    "apikey",
    "otp",
    "recoverycode",
    "jwt",
)


def _is_secret_field_name(name: str) -> bool:
    """An ``*_id`` is a reference, not the secret: ``api_key_id`` is what replaces ``api_key``."""
    if name == "id" or name.endswith("_id"):
        return False
    normalized = name.lower().replace("_", "")
    return any(fragment in normalized for fragment in _SECRET_FRAGMENTS)


def _refuse_secret_fields(cls: type) -> None:
    """Fail at class creation, before any fact is written; the repository's write-time mask is
    only the fallback."""
    for name in _annotation_names(cls):
        if _is_secret_field_name(name):
            raise TypeError(
                f"{cls.__name__} declares field {name!r}, which looks like secret material. "
                "A business event is persisted to the append-only journal — kept for good, "
                "readable by the org's members under RLS, exportable — the opposite of a "
                "secret's lifecycle, so a secret may not be an event field. Carry the "
                f"subject's id instead (e.g. {name}_id) and let the durable handler re-read "
                "the current state off it."
            )


def _annotation_names(cls: type) -> set[str]:
    """Annotated names on ``cls`` and its bases: ``fields()`` is not available before
    ``@dataclass`` runs."""
    names: set[str] = set()
    for klass in cls.__mro__:
        names.update(getattr(klass, "__annotations__", {}))
    return names


@dataclass(frozen=True, kw_only=True)
class BusinessEvent:
    """Base for every recorded domain event. ``kw_only`` lets subclasses add required fields
    after the base's optional ones.

    ``entity_id`` is the concerned entity's pk; ``entity_name`` its readable name (a todo title,
    an invitee's email), absent when the subject is only an id.

    ``created_at`` is set by the journal, not the emitter: ``None`` when emitted, filled on the
    event a consumer receives, so a reaction delayed by retries still knows when the fact happened.
    """

    user_id: uuid.UUID | None = None
    entity_id: uuid.UUID | None = None
    entity_name: str | None = None
    created_at: datetime | None = None

    app_name: ClassVar[AppName] = ""
    verb: ClassVar[str] = ""
    kind: ClassVar[str] = ""
    icon: ClassVar[PhosphorIcon] = "circle"

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Give a concrete subclass its ``kind`` and register it in the catalog. An app mixin with
        no verb stays out."""
        super().__init_subclass__(**kwargs)
        _refuse_secret_fields(cls)
        if cls.app_name and cls.verb:
            cls.kind = f"{cls.app_name}.{cls.verb}"
        if cls.kind:
            catalog.register(cls)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Rebuild the event from a stored record, ignoring keys that are not fields
        (``event_id``, ``user_name``) and parsing back uuids and datetimes. A value that does not
        parse (a redacted ``"***"``) is kept as is.

        A NULL in a required field raises ``TypeError``; the listener logs and skips that fact."""
        optional = {f.name for f in fields(cls) if f.default is not MISSING}
        names = {f.name for f in fields(cls)}
        kept = {k: v for k, v in payload.items() if k in names and (v is not None or k in optional)}
        for target, parse in _REPARSERS.items():
            for key in _fields_carrying(cls, target):
                value = kept.get(key)
                if isinstance(value, str):
                    with contextlib.suppress(ValueError):
                        kept[key] = parse(value)
        return cls(**kept)


@dataclass(frozen=True, kw_only=True)
class OrgScoped:
    """Mixin for a fact inside an organization: ``org_id`` is required, since a fact without it
    would be hidden by RLS from the org it concerns. A server-wide fact leaves the mixin off.

    Twin of the ORM mixin in ``apps.shared.persistence.base``, but a dataclass itself: dataclasses
    only collect fields from dataclass bases.
    """

    org_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class EntityCreated(BusinessEvent):
    """``kind`` becomes ``"<app>.created"``."""

    verb: ClassVar[str] = "created"


@dataclass(frozen=True, kw_only=True)
class EntityUpdated(BusinessEvent):
    """``kind`` becomes ``"<app>.updated"``."""

    verb: ClassVar[str] = "updated"


@dataclass(frozen=True, kw_only=True)
class EntityDeleted(BusinessEvent):
    """``kind`` becomes ``"<app>.deleted"``."""

    verb: ClassVar[str] = "deleted"
