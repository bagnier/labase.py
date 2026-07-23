"""Delivery scans — the listener's plumbing over the trail (claim/mark/scan + the consumed ledger).

Raw ``text()`` on purpose: queue-like plumbing whose locking (``SKIP LOCKED``, ``ON CONFLICT``)
reads best as SQL, and it touches columns/tables kept off the fact model (``dispatched_at``, the
``consumed`` ledger).
"""

from typing import Any

from sqlalchemy import text

from apps.shared.events.repository._base import _EventSQL

_CLAIM = text(
    "SELECT id, kind, level, icon, user_id, org_id, entity_id, payload "
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
    async def claim_undispatched(self, batch: int) -> list[dict[str, Any]]:
        """``SKIP LOCKED`` so N instances never double-claim; the caller marks them dispatched in
        the same transaction."""
        result = await self.session.execute(_CLAIM, {"batch": batch})
        return [dict(r) for r in result.mappings()]

    async def mark_dispatched(self, ids: list[int]) -> None:
        await self.session.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    async def scan_spread(self, cursor: int, kinds: list[str]) -> list[dict[str, Any]]:
        """No lock, no dispatch mark — a ``spread`` handler runs on *every* instance, each replaying
        off its own cursor."""
        result = await self.session.execute(_SPREAD_SCAN, {"cursor": cursor, "kinds": kinds})
        return [dict(r) for r in result.mappings()]

    async def already_consumed(self, topic: str, event_id: int) -> bool:
        """Insert-or-nothing against the ``consumed`` ledger — the idempotency substrate for
        at-least-once ``bus.on`` delivery. ``True`` means this pair is a re-delivery. Runs on the
        handler's session, so it commits/rolls back with the handler's own writes."""
        result = await self.session.execute(
            text(
                "INSERT INTO consumed (topic, event_id) VALUES (:topic, CAST(:event_id AS bigint)) "
                "ON CONFLICT DO NOTHING RETURNING topic"
            ),
            {"topic": topic, "event_id": event_id},
        )
        return result.first() is None
