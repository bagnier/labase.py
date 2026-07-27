"""Delivery scans — the listener's plumbing over the trail (claim/mark/scan + the consumed ledger).

Raw ``text()`` on purpose: queue-like plumbing whose locking (``SKIP LOCKED``, ``ON CONFLICT``)
reads best as SQL, and it touches columns/tables kept off the fact model (``dispatched_at``, the
``consumed`` ledger).
"""

import uuid
from typing import Any, TypedDict, cast

from sqlalchemy import text

from apps.shared.events.repository._base import _EventSQL

# ── The one serialized shape the whole delivery chain agrees on ────────────────────────────────
#
# A base ``BusinessEvent`` field is stored one of two ways: *lifted* to its own indexed column (so
# RLS, the timeline and full-text search reach it directly), or left in the JSON ``payload``.
# ``LIFTED_COLUMNS`` is the single list of the lifted ones — the source every other list here (and
# ``event_to_log``'s pop loop) derives from, so the four views can't drift apart silently. Add a
# lifted base field here and the SELECTs, the fold-back and the round-trip test all move with it.
LIFTED_COLUMNS: tuple[str, ...] = ("user_id", "org_id", "entity_id", "entity_name")

# What both delivery scans read off a row: its id (dispatch cursor + dedup key), the composed
# ``kind`` (→ the event class), the lifted scoping columns, and the residual JSON ``payload``.
# Not selected: ``icon`` (rides on the reconstructed event) and ``user_name``/``org_name``
# (denormalized for display, not event fields) — so they stay out of the fetch.
TRAIL_COLUMNS: tuple[str, ...] = ("id", "kind", *LIFTED_COLUMNS, "payload")

_SELECT = f"SELECT {', '.join(TRAIL_COLUMNS)} FROM business_events "


class TrailRow(TypedDict):
    """The subset of a ``business_events`` row the delivery path reads — exactly the
    ``TRAIL_COLUMNS`` both ``_CLAIM`` and ``_SPREAD_SCAN`` select. The listener rebuilds the typed
    event from it (``kind`` + lifted scoping columns + the JSON ``payload``); ``id`` doubles as the
    dispatch cursor and dedup key. Its keys are pinned to ``TRAIL_COLUMNS`` by a test, so the static
    type and the runtime column source can't diverge."""

    id: uuid.UUID
    kind: str
    user_id: uuid.UUID | None
    org_id: uuid.UUID | None
    entity_id: uuid.UUID | None
    entity_name: str | None  # a base field of every event, lifted to its own column
    payload: dict[str, Any] | None


_CLAIM = text(
    _SELECT + "WHERE dispatched_at IS NULL ORDER BY id FOR UPDATE SKIP LOCKED LIMIT :batch"
)

_SPREAD_SCAN = text(_SELECT + "WHERE id > :cursor AND kind = ANY(:kinds) ORDER BY id")


def task_payload(row: TrailRow) -> dict[str, Any]:
    """Rebuild the async-consumer payload from a claimed row: the residual JSON ``payload`` plus the
    lifted columns folded back in (a uuid column stringified — the queue json-encodes it, and
    ``from_payload`` re-parses it), plus the row id as the dedup ``event_id``. The fold-back walks
    ``LIFTED_COLUMNS`` rather than naming each column, so it is one edit away from the SELECTs and
    the TrailRow it reads. Lives here, beside the columns it mirrors; the listener imports it."""
    # A plain-mapping view of the row: the fold indexes by a runtime column name, which a TypedDict
    # (literal keys only) cannot be subscripted with — the row already arrived as a dict off the scan.
    cells = cast(dict[str, Any], row)
    payload = dict(cells["payload"] or {})
    for col in LIFTED_COLUMNS:
        value = cells[col]
        payload[col] = str(value) if isinstance(value, uuid.UUID) else value
    payload["event_id"] = str(cells["id"])  # the dedup key (uuid; the queue json-encodes it)
    return payload


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
