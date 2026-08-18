"""The business-events repository — the one owner of ``business_events``.

:class:`EventRepository` is :class:`~apps.shared.persistence.repository.BaseRepository` over
:class:`BusinessEventRecord`, and holds every query against the journal in one place:

- **write** — append a fact through the SECURITY DEFINER writer, plus the single ``event →
  record`` mapping (no column dict in between);
- **delivery** — the listener's claim / mark / scan and the ``consumed_events`` ledger;
- **read** — the RLS-scoped ``search`` and ``daily_counts`` behind the activity surfaces.

Humanizing a record for a surface is not here: that is :mod:`apps.shared.events.activity`.
"""

import json
import uuid
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any, ClassVar

import structlog
from sqlalchemy import Date, Text, cast, func, or_, select
from sqlalchemy import text as sql_text  # aliased: `search` takes a `text` filter of its own
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.contextvars import get_contextvars

from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.types import BusinessEvent, OrgScoped, _is_secret_field_name
from apps.shared.persistence.repository import BaseRepository

log = structlog.get_logger("labase.business_events")

# The base ``BusinessEvent`` fields stored in their own indexed column rather than in the JSON
# ``payload`` — which is what lets RLS, the timeline and full-text search reach them directly.
# ``event_to_record`` pops exactly these out of the payload and ``task_payload`` folds exactly these
# back in, both walking this tuple, so the two halves cannot drift apart.
LIFTED_COLUMNS: tuple[str, ...] = ("user_id", "org_id", "entity_id", "entity_name")

# The journal's one writer: a SECURITY DEFINER function that inserts as its owner, so the request's
# ``authenticated`` session writes the fact atomically with its mutation without a table grant
# PostgREST would share. ``kind`` is generated and ``id``/``created_at`` keep their column defaults,
# so none of the three is passed.
_RECORD = sql_text(
    "SELECT record_business_event("
    ":app_name, :verb, :icon, :user_id, :user_name, :org_id, :org_name, "
    ":entity_id, :entity_name, :request_id, :request_name, :ip_address, CAST(:payload AS jsonb))"
)


# ── Write: append a fact, and the one event → record mapping ─────────────────────────────────────


async def _append_record(session: AsyncSession, record: BusinessEventRecord) -> None:
    """Append a fact through the writer function on ``session`` (its transaction). ``record`` is the
    typed carrier :func:`event_to_record` (or the explicit-column writer) already built — the one
    ``event → record`` shape — read off as the function's arguments."""
    await session.execute(
        _RECORD,
        {
            "app_name": record.app_name,
            "verb": record.verb,
            "icon": record.icon,
            "user_id": record.user_id,
            "user_name": record.user_name,
            "org_id": record.org_id,
            "org_name": record.org_name,
            "entity_id": record.entity_id,
            "entity_name": record.entity_name,
            "request_id": record.request_id,
            "request_name": record.request_name,
            "ip_address": record.ip_address,
            "payload": json.dumps(record.payload or {}),
        },
    )


def _fact_payload(event: BusinessEvent) -> dict[str, Any]:
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if _is_secret_field_name(f.name):
            # Defence in depth: ``__init_subclass__`` already refuses a secret-named event field, so
            # reaching here means one slipped past (a raw or legacy writer). Mask it *and* shout — a
            # silent mask is how the leak stayed invisible; an error is what gets it fixed.
            if value is not None:
                log.error("business_event.secret_field_masked", field=f.name, kind=event.kind)
            payload[f.name] = "***" if value is not None else None
        elif isinstance(value, uuid.UUID):
            payload[f.name] = str(value)  # json-safe: stdlib json can't serialize a uuid.UUID
        elif isinstance(value, datetime):
            payload[f.name] = value.isoformat()  # json-safe; from_payload re-parses it back
        else:
            payload[f.name] = value
    return payload


def event_to_record(
    event: BusinessEvent, *, user_name: str | None = None, org_name: str | None = None
) -> BusinessEventRecord:
    """The one ``event → record`` conversion. Scoping (user/org/entity) and the readable names are
    lifted to their own columns — so RLS, the timeline and full-text search reach them directly —
    leaving only the (redacted) rest in ``payload``; ``ip_address``/``request_id`` ride in from
    the request contextvars."""
    ctx = get_contextvars()
    request_id = ctx.get("request_id")
    payload = _fact_payload(event)
    for lifted in LIFTED_COLUMNS:
        payload.pop(lifted, None)
    # Dropped, not carried: the emitter's created_at is always None, and passing it would shadow the
    # column default that is the fact's one clock.
    payload.pop("created_at", None)
    return BusinessEventRecord(
        app_name=event.app_name,
        verb=event.verb,
        icon=event.icon,
        user_id=event.user_id,
        ip_address=ctx.get("ip"),
        # Scope is carried by the event's type, not by every event: only an OrgScoped fact names
        # an org. The column stays nullable — a server-wide fact legitimately has none.
        org_id=event.org_id if isinstance(event, OrgScoped) else None,
        entity_id=event.entity_id,
        # The contextvar carries a str (structlog serializes it); the column is a uuid.
        request_id=uuid.UUID(request_id) if request_id else None,
        request_name=ctx.get("request_name"),
        payload=payload,
        user_name=user_name,
        entity_name=event.entity_name,
        org_name=org_name,
    )


# ── Delivery: what the listener reads off the journal ────────────────────────────────────────────


def task_payload(record: BusinessEventRecord) -> dict[str, Any]:
    """Rebuild the async-consumer payload from a claimed record: the residual JSON ``payload`` plus
    the lifted columns folded back in (a uuid stringified — the queue json-encodes it, and
    ``from_payload`` re-parses it), the two correlation keys, and the record id as the dedup key and
    causation id. The fold-back walks ``LIFTED_COLUMNS`` rather than naming each column, so it stays
    one edit away from the pop loop it mirrors; the listener imports it.

    Both correlation keys ride as strings the queue can json-encode. ``created_at`` rebuilds onto
    the event; ``request_id`` is not an event field at all — the delivery wrapper reads it here to
    bind the reaction's log context, and ``from_payload`` then drops it."""
    payload = dict(record.payload or {})
    for column in LIFTED_COLUMNS:
        value = getattr(record, column)
        payload[column] = str(value) if isinstance(value, uuid.UUID) else value
    payload["created_at"] = record.created_at.isoformat() if record.created_at else None
    payload["request_id"] = str(record.request_id) if record.request_id else None
    payload["event_id"] = str(record.id)
    return payload


class EventRepository(BaseRepository[BusinessEventRecord]):
    """All ``business_events`` SQL, bound to one session.

    The two delivery scans read whole :class:`BusinessEventRecord` objects: the journal already has
    a typed shape, so the delivery path reads it rather than re-deriving a narrower one of its own.
    What stays raw ``sql_text()`` is the plumbing proper — the ``dispatched_at`` cursor,
    deliberately left off the fact model, and the ``consumed_events`` ledger, whose
    ``ON CONFLICT`` reads best as SQL.
    """

    model: ClassVar[type[BusinessEventRecord]] = BusinessEventRecord

    # ── Write ────────────────────────────────────────────────────────────────────────────────

    async def record(self, event: BusinessEvent) -> None:
        """Append a typed event to the journal on the bound session; the caller commits."""
        org_id = event.org_id if isinstance(event, OrgScoped) else None
        user_name, org_name = await self.pinned_names(event.user_id, org_id)
        await _append_record(
            self.session, event_to_record(event, user_name=user_name, org_name=org_name)
        )

    async def pinned_names(
        self, user_id: uuid.UUID | None, org_id: uuid.UUID | None
    ) -> tuple[str | None, str | None]:
        """Resolve the actor's handle and the org's name *now*, to store them on the record.

        One round trip for both: the write path already sat on a query for the handle, and a second
        one per emitted fact would double the cost of every business mutation. Both are read on the
        caller's session, so they see the same transaction the fact commits with.

        Profiles are ``own read`` under RLS, so a member cannot resolve a co-member's handle at read
        time; an org can be renamed or deleted outright. Pinning both here is what keeps the journal
        legible later."""
        if not user_id and not org_id:
            return None, None
        try:
            names = (
                await self.session.execute(
                    sql_text(
                        "select (select handle from profiles where user_id = :u),"
                        "       (select name from organizations where id = :o)"
                    ),
                    {"u": user_id, "o": org_id},
                )
            ).first()
        except Exception:
            return None, None
        return (names[0], names[1]) if names else (None, None)

    # ── Delivery ─────────────────────────────────────────────────────────────────────────────

    async def claim_undispatched(self, batch: int) -> list[BusinessEventRecord]:
        """``SKIP LOCKED`` so N instances never double-claim; the caller marks them dispatched in
        the same transaction. ``dispatched_at`` is queue mechanics, not part of what happened, so
        the model does not map it (see :mod:`apps.shared.events.models`) — hence the raw predicate
        in an otherwise ORM query."""
        claimed = await self.session.scalars(
            select(BusinessEventRecord)
            .where(sql_text("dispatched_at IS NULL"))
            .order_by(BusinessEventRecord.id)
            .with_for_update(skip_locked=True)
            .limit(batch)
        )
        return list(claimed)

    async def mark_dispatched(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(
            sql_text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
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
        """Insert-or-nothing against the ``consumed_events`` ledger — the idempotency substrate for
        at-least-once ``bus.on`` delivery. ``True`` means this pair is a re-delivery. Runs on the
        handler's session, so it commits/rolls back with the handler's own writes. ``event_id`` is
        the journal record's uuid — it arrives as a string when replayed off the JSON queue, so the
        ``CAST(... AS uuid)`` normalizes both forms."""
        result = await self.session.execute(
            sql_text(
                "INSERT INTO consumed_events (consumer, event_id) "
                "VALUES (:consumer, CAST(:event_id AS uuid)) "
                "ON CONFLICT DO NOTHING RETURNING consumer"
            ),
            {"consumer": topic, "event_id": event_id},
        )
        return result.first() is None

    # ── Read: RLS-scoped, for the activity surfaces ──────────────────────────────────────────

    async def search(
        self,
        *,
        org_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        entity_id: uuid.UUID | None = None,
        request_id: uuid.UUID | None = None,
        app: str | None = None,
        text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BusinessEventRecord]:
        """Newest-first read under the filters. RLS already scopes the journal to the reader (self
        + orgs); the ``user_id``/``org_id`` filters narrow to one feed on top. ``app`` matches the
        record's own ``app_name`` column — an equality, not a scan of the composed kind's prefix."""
        query = (
            select(BusinessEventRecord)
            .order_by(BusinessEventRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if org_id:
            query = query.where(BusinessEventRecord.org_id == org_id)
        if user_id:
            query = query.where(BusinessEventRecord.user_id == user_id)
        if entity_id:
            query = query.where(BusinessEventRecord.entity_id == entity_id)
        if request_id:
            query = query.where(BusinessEventRecord.request_id == request_id)
        if app:
            query = query.where(BusinessEventRecord.app_name == app)
        if text:
            like = f"%{text}%"
            query = query.where(
                or_(
                    BusinessEventRecord.kind.ilike(like),
                    cast(BusinessEventRecord.payload, Text).ilike(like),
                )
            )
        if from_dt:
            query = query.where(BusinessEventRecord.created_at >= from_dt)
        if to_dt:
            query = query.where(BusinessEventRecord.created_at <= to_dt)
        return list(await self.session.scalars(query))

    async def daily_counts(
        self,
        *,
        user_id: uuid.UUID | None = None,
        org_id: uuid.UUID | None = None,
        days: int = 366,
    ) -> dict[date, int]:
        """Per-day counts for the contribution calendar. Missing days don't appear — the calendar
        builder fills the gaps. RLS-scoped like :meth:`search`."""
        since = clock.now() - timedelta(days=days)
        day = cast(BusinessEventRecord.created_at, Date)
        query = (
            select(day, func.count()).where(BusinessEventRecord.created_at >= since).group_by(day)
        )
        if user_id:
            query = query.where(BusinessEventRecord.user_id == user_id)
        if org_id:
            query = query.where(BusinessEventRecord.org_id == org_id)
        per_day = await self.session.execute(query)
        return {d: n for d, n in per_day.all()}
