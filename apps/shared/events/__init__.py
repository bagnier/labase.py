"""The event subsystem — one cohesive package of focused modules.

A business event is a frozen dataclass (``types``). The bus (``bus``) emits it — persisting the
fact to the append-only trail through the one SQL owner, the ``repository`` (which the ``store``
write path and timeline projection sit on). Durable async consumers ride the ``outbox`` registry,
delivered off the log by the ``listener`` after commit.

This ``__init__`` re-exports only the lightweight **vocabulary** so declaration sites can keep
``from apps.shared.events import BusinessEvent`` without dragging in SQLAlchemy or the DB engine —
importing a type must stay cheap. The bus, repository, store, outbox and listener are reached at
their submodule paths (``apps.shared.events.bus`` / ``.repository`` / ``.store`` / …).
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
