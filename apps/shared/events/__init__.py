"""Business events (AGENTS: business events are facts, not sagas).

- ``types``: the event classes; ``catalog``: which events exist, by stored ``kind``.
- ``bus``: declare, emit, subscribe; ``wiring``: what this process's mounts activated.
- ``repository``: the only writer and reader of ``business_events``.
- ``listener``: delivers reactions off the journal after commit.
- ``activity``: the journal as a user-facing feed (the console's view is ``apps.timeline``).

Only the event types are re-exported here, so declaring an event never imports SQLAlchemy.
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
