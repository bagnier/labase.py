"""Business events — the typed vocabulary of "something happened".

A business event is a frozen dataclass persisted to the ``business_events`` journal by the bus's
``emit`` — no handler runs at emit; the listener dispatches by type off the journal after commit. It
declares only who acted (``user_id``) and which org it concerns (``org_id``); the write path
enriches ``ip_address``/``request_id`` from the request contextvars at write time, while
``kind``/``icon`` are the event's own class metadata.

Most mutations are CRUD, so the ``EntityCreated``/``EntityUpdated``/``EntityDeleted`` abstracts
derive the event ``kind`` (``"<app>.<verb>"``, e.g. ``"todo.created"``) from a one-line per-app
mixin — no ``kind`` string is hand-written::

    class TodoEvent(OrgScoped, BusinessEvent):
        app_name = "todo"

    @dataclass(frozen=True, kw_only=True)
    class TodoCreated(TodoEvent, EntityCreated):
        title: str

Non-CRUD actions (sign-in, a member joining, a page being published) subclass
:class:`BusinessEvent` directly and spell out their own ``verb`` — never a dotted ``kind``, which is
always the composition of the two halves, here and on the journal alike (a generated column).
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

# What the queue's JSON encoding turns a field into, and how to undo it: a uuid rides as its string
# form, a datetime as an ISO one (both written that way by ``event_to_record``). One entry per
# serialized type, so adding a third — a ``date``, a ``Decimal`` — is one line rather than a lookup
# helper *and* a re-parse loop that must be kept in step with it.
_REPARSERS: dict[type, Callable[[str], Any]] = {
    uuid.UUID: uuid.UUID,
    datetime: datetime.fromisoformat,
}


@cache
def _fields_carrying(cls: type[BusinessEvent], target: type) -> frozenset[str]:
    """The dataclass fields whose annotation carries ``target`` — it *is* ``target``, or a union
    that includes it (``uuid.UUID | None``, ``datetime | None``). Resolved once per class and type,
    so any DTO round-trips without a hand-maintained field list."""
    hints = typing.get_type_hints(cls)
    return frozenset(
        f.name
        for f in fields(cls)
        if (hint := hints.get(f.name)) is target or target in typing.get_args(hint)
    )


# Field-name fragments that mark *secret material*, matched against the field name with its
# underscores stripped — so ``api_key`` / ``access_token`` / ``recovery_code`` are each caught by a
# single fragment.
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
    """Whether a field name looks like it carries secret material — as opposed to a mere *id
    reference* to a secret-bearing entity. ``api_key_id`` (the api key's pk) is precisely the
    recommended alternative to ``api_key`` (its plaintext), so a name that is ``id`` or ends in
    ``_id`` is never a violation; everything else is matched against :data:`_SECRET_FRAGMENTS`."""
    if name == "id" or name.endswith("_id"):
        return False
    normalized = name.lower().replace("_", "")
    return any(fragment in normalized for fragment in _SECRET_FRAGMENTS)


def _refuse_secret_fields(cls: type) -> None:
    """Refuse a field that looks like secret material, at class creation — so a violation is a
    definition error, never a written fact. The write-time mask in the repository is only the
    last-resort net behind this one."""
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
    """Every annotated name on ``cls`` and its bases — read at class-creation time, before the
    ``@dataclass`` transform runs (so ``fields()`` is not yet available). Only the names matter for
    the secret check, so string vs. resolved annotations (``from __future__``) is irrelevant."""
    names: set[str] = set()
    for klass in cls.__mro__:
        names.update(getattr(klass, "__annotations__", {}))
    return names


@dataclass(frozen=True, kw_only=True)
class BusinessEvent:
    """Base for every recorded domain event. ``kw_only`` so subclasses may add required payload
    fields without tripping dataclass default-ordering against the base's optional scoping.

    ``entity_id`` is the concerned entity's own uuid pk, which is what correlates a fact with the
    thing it changed; ``entity_name`` is the readable name shown beside it (a todo title, an org
    name, an invitee's email address). A subject that is only an id — an account or membership
    action — carries no name, just the id.

    ``created_at`` is not the emitter's to fill: the journal column is the one clock, so the field
    is ``None`` on the event handed to :meth:`~apps.shared.events.bus.EventBus.emit` and populated
    only on the one a consumer receives, rebuilt from the record. That is what lets a reaction
    reason about *when the fact happened*, not when it was delivered — which a retry, or a parked
    then resumed task, pushes minutes or days later.

    ``app_name``/``verb``/``kind``/``icon`` are class-level, so they identify the event type
    without ever entering an instance's payload.
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
        """Compose the concrete subclass's ``kind`` and enter it in the catalog, which is what
        lets the listener rebuild a typed event from a stored record. An abstract base — an app
        mixin with no verb — composes nothing and stays out."""
        super().__init_subclass__(**kwargs)
        _refuse_secret_fields(cls)
        if cls.app_name and cls.verb:
            cls.kind = f"{cls.app_name}.{cls.verb}"
        if cls.kind:
            catalog.register(cls)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Rebuild the event from a stored record — dropping transport-only keys (``event_id``, the
        denormalized ``user_name`` handle) that aren't event fields, and undoing the task queue's
        JSON encoding on every field :data:`_REPARSERS` covers. The re-parse is generic (driven by
        the field annotations) and defensive: a value that no longer parses — a redacted ``"***"``
        token where a uuid stood — is left as-is rather than crashing the rebuild. Both delivery
        paths use this.

        A stored NULL is dropped along with them, so the dataclass raises rather than hand back an
        event whose required scope is ``None``: a fact whose column is empty — written by a raw
        writer, or before the field became required — fails the rebuild here, and the listener's
        guard logs and skips it, which is the one place that decision belongs."""
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
    """Mixin for a fact that only exists *inside* an organization — its ``org_id`` is required.

    The twin of the ORM mixin of the same name (``apps.shared.persistence.base``), which puts the
    same non-nullable ``org_id`` on org-owned tables; an event composes it the way a model does
    (``class TodoEvent(OrgScoped, BusinessEvent)``). Scope belongs to the *type*: a server-wide
    fact (an admin grant, an issue) has no org field to leave empty, and an org fact cannot be
    emitted without naming its org — which would otherwise persist a fact that RLS then hides from
    the very org it concerns.

    Unlike the ORM twin this must itself be a dataclass: SQLAlchemy reads annotations off a bare
    mixin, ``dataclasses`` only collects fields from bases that are already dataclasses.
    """

    org_id: uuid.UUID


@dataclass(frozen=True, kw_only=True)
class EntityCreated(BusinessEvent):
    """An entity was created — ``kind`` becomes ``"<entity>.created"``. The created entity's id
    rides on the base's ``entity_id``, its display name on ``entity_name``. Scope is orthogonal:
    compose ``OrgScoped`` for an org-owned entity, leave it off for a server-wide one."""

    verb: ClassVar[str] = "created"


@dataclass(frozen=True, kw_only=True)
class EntityUpdated(BusinessEvent):
    """An entity was updated — ``kind`` becomes ``"<entity>.updated"``."""

    verb: ClassVar[str] = "updated"


@dataclass(frozen=True, kw_only=True)
class EntityDeleted(BusinessEvent):
    """An entity was deleted — ``kind`` becomes ``"<entity>.deleted"``."""

    verb: ClassVar[str] = "deleted"
