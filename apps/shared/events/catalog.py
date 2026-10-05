"""Which event classes exist, keyed by the ``kind`` the journal stores.

Every concrete event registers itself at class creation, so the catalog is complete once the
modules are imported. A module singleton, like :mod:`apps.shared.clock`: a class exists once per
process, so there is nothing to inject. What a mount activates lives in
:mod:`apps.shared.events.wiring`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # `types` imports this module to register each class; importing it back at runtime would cycle.
    from apps.shared.events.types import BusinessEvent


def _declared_at(cls: type) -> tuple[str, str]:
    """Where a class is written: a re-imported module or a test re-declaring a class inline is the
    same declaration, not a second claimant."""
    return cls.__module__, cls.__qualname__


def _qualified(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


class EventCatalog:
    """Concrete event classes, keyed by the ``kind`` the journal stores."""

    def __init__(self) -> None:
        self._by_kind: dict[str, type[BusinessEvent]] = {}

    def register(self, event_type: type[BusinessEvent]) -> None:
        """Record a concrete event class under its ``kind``.

        Raises ``ValueError`` when another declaration already holds the kind: the listener would
        otherwise rebuild a stored fact into whichever class was imported last. Registering the
        same declaration twice is a no-op."""
        claimed = self._by_kind.get(event_type.kind)
        if claimed is not None and _declared_at(claimed) != _declared_at(event_type):
            raise ValueError(
                f"event kind {event_type.kind!r} is already registered by "
                f"{_qualified(claimed)}; {_qualified(event_type)} cannot claim it too — "
                "a kind must map back to exactly one class for the journal to be reconstructable"
            )
        self._by_kind[event_type.kind] = event_type

    def class_for(self, kind: str) -> type[BusinessEvent] | None:
        """The class that rebuilds a stored record of ``kind``, or ``None`` if unknown."""
        return self._by_kind.get(kind)

    def kinds(self) -> dict[str, type[BusinessEvent]]:
        """A copy of every kind and its class."""
        return dict(self._by_kind)


catalog = EventCatalog()
