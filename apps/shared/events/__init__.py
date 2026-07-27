"""The event subsystem — one cohesive package of focused modules.

A business event is a frozen dataclass (``types``). The bus (``bus``) emits it — persisting the
fact to the append-only trail through the one owner of ``business_events``, the ``repository``
(``EventRepository.record`` writes a typed event as a row; the bus's ``_persist_fact`` chooses the
session). Durable async consumers register via ``bus.on`` and are delivered off the log by the
``listener`` after commit. Reading the trail back for a surface — the humanized activity feed and
contribution calendar — is pure presentation, in ``timeline``.

This ``__init__`` re-exports only the lightweight **vocabulary** so declaration sites can keep
``from apps.shared.events import BusinessEvent`` without dragging in SQLAlchemy or the DB engine —
importing a type must stay cheap. The bus, repository, timeline and listener are reached at their
submodule paths (``apps.shared.events.bus`` / ``.repository`` / ``.timeline`` / ``.listener``).
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
