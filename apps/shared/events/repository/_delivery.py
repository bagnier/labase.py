"""Delivery scans — the listener's plumbing over the trail (claim/mark/scan + the consumed ledger).

Raw ``text()`` on purpose: queue-like plumbing whose locking (``SKIP LOCKED``, ``ON CONFLICT``)
reads best as SQL, and it touches columns/tables kept off the fact model (``dispatched_at``, the
``consumed`` ledger).
"""

import uuid
from typing import Any, TypedDict, cast

from sqlalchemy import text

from apps.shared.events.repository._base import _EventSQL


class TrailRow(TypedDict):
    """The subset of a ``business_events`` row the delivery path reads — exactly what ``_CLAIM``
    and ``_SPREAD_SCAN`` both select. The listener rebuilds the typed event from it (``kind`` +
    scoping columns + the JSON ``payload``); ``id`` doubles as the dispatch cursor and dedup key."""

    id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None
    org_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    payload: dict[str, Any] | None


# Both scans select exactly TrailRow's columns — the listener never reads level/icon off a claimed
# row (they live on the reconstructed event), so they stay out of the fetch.
_CLAIM = text(
    "SELECT id, kind, user_id, org_id, entity_id, payload "
    "FROM business_events "
    "WHERE dispatched_at IS NULL "
    "ORDER BY id "
    "FOR UPDATE SKIP LOCKED "
    "LIMIT :batch"
)

_SPREAD_SCAN = text(
    "SELECT id, kind, user_id, org_id, entity_id, payload "
    "FROM business_events "
    "WHERE id > :cursor AND kind = ANY(:kinds) "
    "ORDER BY id"
)


class _DispatchesEvents(_EventSQL):
    async def claim_undispatched(self, batch: int) -> list[TrailRow]:
        """``SKIP LOCKED`` so N instances never double-claim; the caller marks them dispatched in
        the same transaction."""
        result = await self.session.execute(_CLAIM, {"batch": batch})
        return [cast(TrailRow, dict(r)) for r in result.mappings()]

    async def mark_dispatched(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    async def scan_spread(self, cursor: uuid.UUID, kinds: list[str]) -> list[TrailRow]:
        """No lock, no dispatch mark — a ``spread`` handler runs on *every* instance, each replaying
        off its own cursor."""
        result = await self.session.execute(_SPREAD_SCAN, {"cursor": cursor, "kinds": kinds})
        return [cast(TrailRow, dict(r)) for r in result.mappings()]

    async def already_consumed(self, topic: str, event_id: uuid.UUID | str) -> bool:
        """Insert-or-nothing against the ``consumed`` ledger — the idempotency substrate for
        at-least-once ``bus.on`` delivery. ``True`` means this pair is a re-delivery. Runs on the
        handler's session, so it commits/rolls back with the handler's own writes. ``event_id`` is
        the trail row's uuid — it arrives as a string when replayed off the JSON queue, so the
        ``CAST(... AS uuid)`` normalizes both forms."""
        result = await self.session.execute(
            text(
                "INSERT INTO consumed (topic, event_id) VALUES (:topic, CAST(:event_id AS uuid)) "
                "ON CONFLICT DO NOTHING RETURNING topic"
            ),
            {"topic": topic, "event_id": event_id},
        )
        return result.first() is None
