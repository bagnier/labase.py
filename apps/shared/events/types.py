"""Business events — the typed vocabulary of "something happened".

A business event is a frozen dataclass persisted to the ``business_events`` journal by the bus's
``emit`` — no handler runs at emit; the listener dispatches by type off the journal after commit. It
declares only who acted (``user_id``) and which org it concerns (``org_id``); the write path
enriches ``ip``/``request_id`` from the request contextvars at write time, while
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
from dataclasses import MISSING, dataclass, fields
from datetime import datetime
from functools import cache
from typing import Any, ClassVar, Self

from apps.shared.events.catalog import catalog


def _wants(hint: Any, target: type) -> bool:
    """A field carries ``target`` if its annotation *is* ``target`` or a union that includes it
    (e.g. ``uuid.UUID | None``, ``datetime | None``)."""
    return hint is target or target in typing.get_args(hint)


@cache
def _uuid_fields(cls: type[BusinessEvent]) -> frozenset[str]:
    """The dataclass fields whose type carries a ``uuid.UUID`` — resolved once per class. Drives the
    generic re-parse so any DTO can carry uuids without a hand-maintained field list."""
    hints = typing.get_type_hints(cls)
    return frozenset(f.name for f in fields(cls) if _wants(hints.get(f.name), uuid.UUID))


@cache
def _datetime_fields(cls: type[BusinessEvent]) -> frozenset[str]:
    """The dataclass fields whose type carries a ``datetime`` — the timestamp twin of
    :func:`_uuid_fields`. The queue serializes a datetime to an ISO string, so reconstruction
    re-parses these back, driven by the annotation rather than a hand-kept list."""
    hints = typing.get_type_hints(cls)
    return frozenset(f.name for f in fields(cls) if _wants(hints.get(f.name), datetime))


# Field-name fragments that mark *secret material*. A business event is persisted to the
# append-only journal — kept for good, RLS-readable by the org's members, exportable to
# CSV/NDJSON — the exact inverse of a secret's lifecycle (short-lived, need-to-know, revocable).
# So a secret may not be an event field at all. Underscores are stripped before the match, so
# ``api_key`` / ``access_token`` / ``recovery_code`` are all caught by a single fragment.
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
    fields without tripping dataclass default-ordering against the base's optional scoping."""

    # the actor of the event
    user_id: uuid.UUID | None = None
    # the concerned entity's stable id, for correlation — always its uuid pk
    # it could be a user_id, todo_id, page_id, whateven
    entity_id: uuid.UUID | None = None
    # the subject's readable name — a todo title, an org name, or (when the subject is an email
    # target) an invitee's email. Emit-provided; rides in the payload for display (the timeline's
    # "detail"). A pure-id user subject (account/membership action) carries none — its entity_id is.
    entity_name: str | None = None
    # the instant the fact happened — the journal's own column, *not* an emit-provided value: the
    # emitter never sets it (the journal is the clock, one source), so it is None on the event
    # that is emitted and populated only on the event a consumer receives, rebuilt from the record.
    # That is what lets a reaction reason about *when the fact happened*, not when it was delivered
    # (which a retry or a parked-then-resumed task pushes minutes — or days — later).
    created_at: datetime | None = None

    # Class-level identity/metadata — never instance fields, so they stay out of the payload.
    # The app the event belongs to ("todo", "files"), usually set once by the per-app mixin, and
    # the verb it performs ("created", "signed_in"). Together they *are* the event's identity;
    # ``kind`` below is only their composition.
    app_name: ClassVar[str] = ""
    verb: ClassVar[str] = ""
    kind: ClassVar[str] = ""  # derived — "<app_name>.<verb>", never written by hand
    icon: ClassVar[str] = "circle"  # phosphor name the event OWNS, so shared never maps apps→icons

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        # A secret cannot be an event field: refuse it here, at class definition, so the type system
        # rejects the violation before a fact is ever written (the write-time mask in the repository
        # is only a last-resort net that should now never fire). The message names the alternative.
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
        # A concrete event has both halves (an app_name from its app mixin, a verb of its own):
        # compose its kind. The derivation is unconditional — the journal derives the same way
        # (a generated column), so a hand-written kind would only make the class disagree with the
        # records it is meant to rebuild.
        if cls.app_name and cls.verb:
            cls.kind = f"{cls.app_name}.{cls.verb}"
        # A concrete event (non-empty kind) registers itself in the catalog so the listener can
        # reconstruct it from a stored record. Abstract bases (EntityCreated…, kind "") never do.
        if cls.kind:
            catalog.register(cls)

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Rebuild the event from a stored record — dropping transport-only keys (``event_id``, the
        denormalized ``user_name`` handle) that aren't event fields, and re-parsing every
        uuid-typed field the task queue serialized to a string. The re-parse is generic (driven by
        the field annotations) and defensive: a value that isn't a valid uuid — a redacted ``"***"``
        token — is left as-is rather than crashing the rebuild. Both delivery paths use this."""
        # A stored NULL never satisfies a field the type declares required: dropping it lets the
        # dataclass raise rather than hand back an event whose required scope is None. Facts
        # written before a field became required (or by a raw writer) fail the rebuild here, and
        # the listener's guard logs and skips them — the one place that decision belongs.
        optional = {f.name for f in fields(cls) if f.default is not MISSING}
        names = {f.name for f in fields(cls)}
        kept = {k: v for k, v in payload.items() if k in names and (v is not None or k in optional)}
        for key in _uuid_fields(cls):
            value = kept.get(key)
            if isinstance(value, str):
                with contextlib.suppress(ValueError):
                    kept[key] = uuid.UUID(value)
        for key in _datetime_fields(cls):
            value = kept.get(key)
            if isinstance(value, str):
                with contextlib.suppress(ValueError):
                    kept[key] = datetime.fromisoformat(value)
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
