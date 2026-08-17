"""Delivery scans — the listener's plumbing over the journal (claim/mark/scan + consumed ledger).

The two scans read whole :class:`BusinessEventRecord` objects: the journal already has a typed
shape, so the delivery path reads it rather than re-deriving a narrower one of its own. What stays
raw ``text()`` is the plumbing proper — the ``dispatched_at`` cursor, deliberately left off the fact
model, and the ``consumed`` ledger, whose ``ON CONFLICT`` reads best as SQL.
"""

import uuid
from typing import Any

from sqlalchemy import select, text

from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository._base import _EventSQL

# A base ``BusinessEvent`` field is stored one of two ways: *lifted* to its own indexed column (so
# RLS, the timeline and full-text search reach it directly), or left in the JSON ``payload``. This
# is the single list of the lifted ones — ``event_to_record`` pops exactly these out of the payload
# and ``task_payload`` folds exactly these back in, so the two halves cannot drift apart.
LIFTED_COLUMNS: tuple[str, ...] = ("user_id", "org_id", "entity_id", "entity_name")


def task_payload(record: BusinessEventRecord) -> dict[str, Any]:
    """Rebuild the async-consumer payload from a claimed record: the residual JSON ``payload`` plus
    the lifted columns folded back in (a uuid stringified — the queue json-encodes it, and
    ``from_payload`` re-parses it), the two correlation keys, and the record id as the dedup
    ``event_id``. The fold-back walks ``LIFTED_COLUMNS`` rather than naming each column, so it stays
    one edit away from the pop loop it mirrors; the listener imports it."""
    payload = dict(record.payload or {})
    for column in LIFTED_COLUMNS:
        value = getattr(record, column)
        payload[column] = str(value) if isinstance(value, uuid.UUID) else value
    # Correlation keys ride as strings the queue can json-encode. ``created_at`` rebuilds onto the
    # event (``from_payload`` re-parses it); ``request_id`` is not an event field — the delivery
    # wrapper reads it here to bind the reaction's log context, then ``from_payload`` drops it.
    payload["created_at"] = record.created_at.isoformat() if record.created_at else None
    payload["request_id"] = str(record.request_id) if record.request_id else None
    payload["event_id"] = str(record.id)  # the dedup key + causation id (uuid; queue-encoded)
    return payload


class _DispatchesEvents(_EventSQL):
    async def claim_undispatched(self, batch: int) -> list[BusinessEventRecord]:
        """``SKIP LOCKED`` so N instances never double-claim; the caller marks them dispatched in
        the same transaction. ``dispatched_at`` is queue mechanics, not part of what happened, so
        the model does not map it (see :mod:`apps.shared.events.models`) — hence the raw predicate
        in an otherwise ORM query."""
        claimed = await self.session.scalars(
            select(BusinessEventRecord)
            .where(text("dispatched_at IS NULL"))
            .order_by(BusinessEventRecord.id)
            .with_for_update(skip_locked=True)
            .limit(batch)
        )
        return list(claimed)

    async def mark_dispatched(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    async def scan_spread(self, cursor: uuid.UUID, kinds: list[str]) -> list[BusinessEventRecord]:
        """No lock, no dispatch mark — a ``spread`` handler runs on *every* instance, each replaying
        off its own cursor."""
        found = await self.session.scalars(
            select(BusinessEventRecord)
            .where(BusinessEventRecord.id > cursor, BusinessEventRecord.kind.in_(kinds))
            .order_by(BusinessEventRecord.id)
        )
        return list(found)

    async def already_consumed(self, topic: str, event_id: uuid.UUID | str) -> bool:
        """Insert-or-nothing against the ``consumed`` ledger — the idempotency substrate for
        at-least-once ``bus.on`` delivery. ``True`` means this pair is a re-delivery. Runs on the
        handler's session, so it commits/rolls back with the handler's own writes. ``event_id`` is
        the journal record's uuid — it arrives as a string when replayed off the JSON queue, so the
        ``CAST(... AS uuid)`` normalizes both forms."""
        result = await self.session.execute(
            text(
                "INSERT INTO consumed (topic, event_id) VALUES (:topic, CAST(:event_id AS uuid)) "
                "ON CONFLICT DO NOTHING RETURNING topic"
            ),
            {"topic": topic, "event_id": event_id},
        )
        return result.first() is None
