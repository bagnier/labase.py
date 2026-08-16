"""The event subsystem — one cohesive package of focused modules.

A business event is a frozen dataclass (``types``), and declaring one puts it in the ``catalog`` —
*which facts exist*, keyed by the ``kind`` the trail stores, process-wide from import. What a mount
activates is the other half, in ``wiring``: *which of them this process emits, and who reacts*.

The bus (``bus``) writes that wiring and emits — persisting the fact to the append-only trail
through the one owner of ``business_events``, the ``repository`` (``EventRepository.record`` writes
a typed event as a row on the session the caller names). Durable async consumers register via
``bus.on`` and are delivered off the trail by the ``listener`` after commit, which is the one place
the two halves meet: the catalog says what a row is, the wiring says who wants it. Reading the trail
back for a surface — the humanized activity feed and contribution calendar — is pure presentation,
in ``timeline``.

This ``__init__`` re-exports only the lightweight **vocabulary** so declaration sites can keep
``from apps.shared.events import BusinessEvent`` without dragging in SQLAlchemy or the DB engine —
importing a type must stay cheap. Everything else is reached at its submodule path
(``apps.shared.events.bus`` / ``.catalog`` / ``.wiring`` / ``.repository`` / ``.timeline`` /
``.listener``).
"""

from apps.shared.events.types import (
    BusinessEvent,
    EntityCreated,
    EntityDeleted,
    EntityUpdated,
    OrgScoped,
)

__all__ = [
    "BusinessEvent",
    "EntityCreated",
    "EntityDeleted",
    "EntityUpdated",
    "OrgScoped",
]
