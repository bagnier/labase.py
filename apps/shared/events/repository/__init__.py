"""The business-events repository — the one owner of ``business_events``.

:class:`EventRepository` is :class:`~apps.shared.persistence.repository.BaseRepository` over
:class:`BusinessEventRecord`, composed from three concern modules: ``_write`` (append a fact + the
``event → row`` mapping), ``_delivery`` (the listener's claim/mark/scan + consumed ledger), and
``_read`` (``search``/``daily_counts``). Humanizing rows is elsewhere (``timeline``); so is emit's
session policy (the bus's ``_persist_fact``).

This composition root wires the mixins together and re-exports the public surface, so callers keep
``from apps.shared.events.repository import EventRepository``.
"""

from apps.shared.events.repository._delivery import (
    LIFTED_COLUMNS,
    TRAIL_COLUMNS,
    TrailRow,
    _DispatchesEvents,
    task_payload,
)
from apps.shared.events.repository._read import _ReadsEvents
from apps.shared.events.repository._write import _WritesEvents, event_to_log, insert_business_event


class EventRepository(_WritesEvents, _DispatchesEvents, _ReadsEvents):
    """All ``business_events`` SQL, bound to one session — the three concern mixins composed."""


__all__ = [
    "LIFTED_COLUMNS",
    "TRAIL_COLUMNS",
    "EventRepository",
    "TrailRow",
    "event_to_log",
    "insert_business_event",
    "task_payload",
]
