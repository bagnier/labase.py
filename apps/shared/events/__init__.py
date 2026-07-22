"""The event subsystem — one cohesive package, five focused modules.

A business event is a frozen dataclass (``types``) that the bus (``bus``) both fans out to its
sync handlers *and* persists to the append-only trail (``store``); durable async consumers ride
the ``outbox`` registry, delivered off the log by the ``tailer`` after commit.

This ``__init__`` re-exports only the lightweight **vocabulary** so declaration sites can keep
``from apps.shared.events import BusinessEvent`` without dragging in SQLAlchemy or the DB engine —
importing a type must stay cheap. The store, bus, outbox and tailer are reached at their submodule
paths (``apps.shared.events.store`` / ``.bus`` / ``.outbox`` / ``.tailer``).
"""

from apps.shared.events.types import (
    BusinessEvent,
    EntityCreated,
    EntityDeleted,
    EntityUpdated,
)

__all__ = [
    "BusinessEvent",
    "EntityCreated",
    "EntityDeleted",
    "EntityUpdated",
]
