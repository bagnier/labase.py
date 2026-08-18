"""The event catalog — which facts exist, by their stored name.

One question, one answer: given a dotted ``kind`` off a ``business_events`` record, which
:class:`~apps.shared.events.types.BusinessEvent` subclass rebuilds it. Every concrete event class
registers itself here at class creation (``BusinessEvent.__init_subclass__``), so the catalog is
complete as soon as the modules are imported.

It is a **module singleton, not a collaborator**, and that is the point: a class is defined exactly
once per process, so there is no second catalog to inject and no isolation a test could buy by
passing its own. Reached like :mod:`apps.shared.clock`. What a mount *activates* — which app emits
what, who reacts — has the opposite lifetime and lives next door, in
:mod:`apps.shared.events.wiring`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Deferred to break the definition cycle, not a layering error: an event class registers itself
    # here at creation, so `types` imports this module at runtime, and this one only needs the name
    # `BusinessEvent` to annotate what it stores.
    from apps.shared.events.types import BusinessEvent


def _declared_at(cls: type) -> tuple[str, str]:
    """Where a class is written — the identity the catalog dedupes on, so re-importing a module
    (or re-running a test that declares a class inline) is not mistaken for a second claimant."""
    return cls.__module__, cls.__qualname__


def _qualified(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


class EventCatalog:
    """Concrete event classes, keyed by the ``kind`` the journal stores."""

    def __init__(self) -> None:
        self._by_kind: dict[str, type[BusinessEvent]] = {}

    def register(self, event_type: type[BusinessEvent]) -> None:
        """Record a concrete event class under its ``kind`` — called once per class from
        :meth:`~apps.shared.events.types.BusinessEvent.__init_subclass__`, for reconstruction.

        A kind is the journal's *stored* identity: it is what :meth:`class_for` maps back to a class
        when the listener rebuilds a persisted fact. Two classes claiming one kind would therefore
        replace each other by import order, and a durable consumer would be handed the wrong type —
        so a duplicate is refused here, at import, rather than found in production.

        Duplicate means *a different declaration*, compared by where the class is written, not by
        object identity: a reimported module, or a class defined inside a test body that runs
        twice, re-creates the same declaration and must stay idempotent."""
        claimed = self._by_kind.get(event_type.kind)
        if claimed is not None and _declared_at(claimed) != _declared_at(event_type):
            raise ValueError(
                f"event kind {event_type.kind!r} is already registered by "
                f"{_qualified(claimed)}; {_qualified(event_type)} cannot claim it too — "
                "a kind must map back to exactly one class for the journal to be reconstructable"
            )
        self._by_kind[event_type.kind] = event_type

    def class_for(self, kind: str) -> type[BusinessEvent] | None:
        """The concrete ``BusinessEvent`` subclass for a dotted ``kind``, or ``None`` if unknown —
        lets the listener rebuild a typed event from a persisted ``business_events`` record."""
        return self._by_kind.get(kind)

    def kinds(self) -> dict[str, type[BusinessEvent]]:
        """Every registered kind and its class — a copy, so a reader cannot edit the catalog by
        holding it. This is what pins the shipped vocabulary in ``tests/test_event_vocabulary``."""
        return dict(self._by_kind)


# The process-wide catalog: every event class registers into this one at import.
catalog = EventCatalog()
