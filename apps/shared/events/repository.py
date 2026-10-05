"""Every query against ``business_events``: the write, the listener's delivery, the RLS-scoped
reads. Turning a record into something readable is :mod:`apps.shared.events.activity`'s job.
"""

import json
import uuid
from dataclasses import fields, is_dataclass
from datetime import date, datetime, timedelta
from itertools import takewhile
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

log = structlog.get_logger(__name__)


class MaskedSecret(Exception):
    """A secret-named field reached the write path, past the class-creation check.

    Raised and caught at once only to put a traceback on the warning.
    """


# Event fields stored in their own indexed column, out of ``payload``, for RLS, the Timeline and
# search. ``event_to_record`` pops them and ``task_payload`` folds them back, both from this tuple.
LIFTED_COLUMNS: tuple[str, ...] = ("user_id", "org_id", "entity_id", "entity_name")

# The journal's only writer, a SECURITY DEFINER function: the request's session writes the fact in
# its own transaction without an INSERT grant, which PostgREST would expose on the same role. It
# trusts the given ``user_id``: a durable consumer may record a fact for another actor. Auth routes
# call it on the admin session, having no RLS identity yet; the signup trigger is the one direct
# insert, inside GoTrue's transaction. ``kind``, ``id`` and
# ``created_at`` come from the column definitions.
_RECORD = sql_text(
    "SELECT record_business_event("
    ":app_name, :verb, :icon, :user_id, :user_name, :org_id, :org_name, "
    ":entity_id, :entity_name, :request_id, :request_name, :ip_address, CAST(:payload AS jsonb))"
)


# ── Write: append a fact, and the one event → record mapping ─────────────────────────────────────


async def _append_record(session: AsyncSession, record: BusinessEventRecord) -> None:
    """Append ``record`` through the writer function, in ``session``'s transaction."""
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
            "payload": json.dumps(record.payload),
        },
    )


def _report_masked_secret(field_name: str, kind: str) -> None:
    """A warning, not ``log.exception``: the capture seam would turn it into an issue."""
    try:
        raise MaskedSecret(f"{kind} carries a field named {field_name!r}")
    except MaskedSecret as exc:
        log.warning("business_event.secret_field_masked", exc_info=exc, field=field_name, kind=kind)


def _fact_payload(event: BusinessEvent) -> dict[str, Any]:
    if not is_dataclass(event) or isinstance(event, type):
        return {}
    payload: dict[str, Any] = {}
    for f in fields(event):
        value = getattr(event, f.name)
        if _is_secret_field_name(f.name):
            # Fallback behind ``__init_subclass__``'s refusal: mask, and say so.
            if value is not None:
                _report_masked_secret(f.name, event.kind)
            payload[f.name] = "***" if value is not None else None
        elif isinstance(value, uuid.UUID):
            payload[f.name] = str(value)
        elif isinstance(value, datetime):
            payload[f.name] = value.isoformat()
        else:
            payload[f.name] = value
    return payload


def event_to_record(
    event: BusinessEvent, *, user_name: str | None = None, org_name: str | None = None
) -> BusinessEventRecord:
    """Map an event to its record: :data:`LIFTED_COLUMNS` to columns, the rest (secrets masked)
    to ``payload``, the request's ip and id from the log contextvars."""
    ctx = get_contextvars()
    request_id = ctx.get("request_id")
    payload = _fact_payload(event)
    for lifted in LIFTED_COLUMNS:
        payload.pop(lifted, None)
    # Always None at emit; the column default sets it.
    payload.pop("created_at", None)
    return BusinessEventRecord(
        app_name=event.app_name,
        verb=event.verb,
        icon=event.icon,
        user_id=event.user_id,
        ip_address=ctx.get("ip"),
        org_id=event.org_id if isinstance(event, OrgScoped) else None,
        entity_id=event.entity_id,
        request_id=uuid.UUID(request_id) if request_id else None,
        request_name=ctx.get("request_name"),
        payload=payload,
        user_name=user_name,
        entity_name=event.entity_name,
        org_name=org_name,
    )


# ── Delivery: what the listener reads off the journal ────────────────────────────────────────────


def task_payload(record: BusinessEventRecord) -> dict[str, Any]:
    """The queue payload for a consumer of ``record``: the event's fields as JSON-safe values,
    plus ``event_id`` (dedup key) and ``request_id``, which the delivery wrapper binds to the
    reaction's logs and ``from_payload`` ignores."""
    payload = dict(record.payload)
    for column in LIFTED_COLUMNS:
        value = getattr(record, column)
        payload[column] = str(value) if isinstance(value, uuid.UUID) else value
    payload["created_at"] = record.created_at.isoformat() if record.created_at else None
    payload["request_id"] = str(record.request_id) if record.request_id else None
    payload["event_id"] = str(record.id)
    return payload


class EventRepository(BaseRepository[BusinessEventRecord]):
    """All ``business_events`` SQL, bound to one session. Raw SQL only for the unmapped
    ``checked_at`` marker, the per-topic ``event_dispatch_cursors`` and the ``consumed_events`` /
    ``dispatched_consumers`` ledgers."""

    model: ClassVar[type[BusinessEventRecord]] = BusinessEventRecord

    # ── Write ────────────────────────────────────────────────────────────────────────────────

    async def record(self, event: BusinessEvent) -> None:
        """Append ``event`` to the journal; the caller commits."""
        org_id = event.org_id if isinstance(event, OrgScoped) else None
        user_name, org_name = await self.pinned_names(event.user_id, org_id)
        await _append_record(
            self.session, event_to_record(event, user_name=user_name, org_name=org_name)
        )

    async def pinned_names(
        self, user_id: uuid.UUID | None, org_id: uuid.UUID | None
    ) -> tuple[str | None, str | None]:
        """The actor's and the org's names as they read now, in one query on the caller's session.

        Falls back to the email when the account has no ``handle`` yet: it gets one on its first
        visit to ``/profile`` (``ProfileRepository.auto_handle``)."""
        if not user_id and not org_id:
            return None, None
        try:
            names = (
                await self.session.execute(
                    sql_text(
                        "select (select coalesce(handle, email) from profiles where user_id = :u),"
                        "       (select name from organizations where id = :o)"
                    ),
                    {"u": user_id, "o": org_id},
                )
            ).first()
        except Exception as exc:
            # The fact is still written, without names: losing them for good beats failing the
            # action.
            log.warning("business_event.names_unpinned", exc_info=exc)
            return None, None
        return (names[0], names[1]) if names else (None, None)

    # ── Delivery ─────────────────────────────────────────────────────────────────────────────

    async def claim_unchecked(self, batch: int) -> list[BusinessEventRecord]:
        """Lock up to ``batch`` unchecked facts, skipping those another instance holds; the caller
        marks them checked in the same transaction. Bounds the routability check only: delivery
        runs off each topic's cursor (:meth:`facts_above_cursor`)."""
        claimed = await self.session.scalars(
            select(BusinessEventRecord)
            .where(sql_text("checked_at IS NULL"))
            .order_by(BusinessEventRecord.id)
            .with_for_update(skip_locked=True)
            .limit(batch)
        )
        return list(claimed)

    async def mark_checked(self, ids: list[uuid.UUID]) -> None:
        await self.session.execute(
            sql_text("UPDATE business_events SET checked_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    _NIL_CURSOR: ClassVar[uuid.UUID] = uuid.UUID(int=0)

    async def lock_dispatch_cursor(self, topic: str) -> uuid.UUID | None:
        """The topic's own cursor, locked for this tick — ``None`` when another instance already
        holds it (skipped this tick, retried next). A topic seen for the first time anywhere gets
        a fresh row at the nil cursor, so it starts owed every fact recorded before it existed —
        an app switched on, then restarted, still catches up on what it missed."""
        await self.session.execute(
            sql_text(
                "INSERT INTO event_dispatch_cursors (topic, cursor) VALUES (:topic, :nil) "
                "ON CONFLICT (topic) DO NOTHING"
            ),
            {"topic": topic, "nil": self._NIL_CURSOR},
        )
        return await self.session.scalar(
            sql_text(
                "SELECT cursor FROM event_dispatch_cursors "
                "WHERE topic = :topic FOR UPDATE SKIP LOCKED"
            ),
            {"topic": topic},
        )

    async def advance_dispatch_cursor(self, topic: str, cursor: uuid.UUID) -> None:
        await self.session.execute(
            sql_text("UPDATE event_dispatch_cursors SET cursor = :cursor WHERE topic = :topic"),
            {"cursor": cursor, "topic": topic},
        )

    async def dispatch_consumer(self, event_id: uuid.UUID, topic: str) -> bool:
        """Insert-or-nothing against the ``dispatched_consumers`` ledger — ``True`` the first time
        this (event, topic) pair is seen, which is when the caller must actually enqueue the task;
        a re-check before the topic's cursor has caught up finds the row and no-ops."""
        result = await self.session.execute(
            sql_text(
                "INSERT INTO dispatched_consumers (event_id, topic) VALUES (:event_id, :topic) "
                "ON CONFLICT DO NOTHING RETURNING event_id"
            ),
            {"event_id": event_id, "topic": topic},
        )
        return result.first() is not None

    async def settled_before(self, settle_seconds: float) -> datetime:
        """The cutoff a cursor may safely advance to, read once and shared across every cursor a
        tick moves (:meth:`facts_above_cursor` is called once per durable consumer, and reading
        this itself per call would cost one more round trip per topic for a value none of them own
        — it names how long a transaction may stay open, not who is asking)."""
        return await self.session.scalar(
            sql_text("SELECT now() - make_interval(secs => :settle)"),
            {"settle": settle_seconds},
        )

    async def facts_above_cursor(
        self, cursor: uuid.UUID, kinds: list[str], settled_before: datetime
    ) -> tuple[list[BusinessEventRecord], uuid.UUID]:
        """The facts above ``cursor`` whose kind is one of ``kinds``, and the cursor its reader may
        safely take next — shared by ``spread`` (a cursor per process, in memory) and the durable
        per-consumer backlog (a cursor per topic, in ``event_dispatch_cursors``): both replay off a
        cursor of their own, so both share the one hazard a cursor has and a claim does not.

        What a cursor may not do is outrun the commits. A key is minted at INSERT, not at commit,
        so a slow transaction commits *after* a quick one that started later: the slow fact
        surfaces holding the lower key, below a cursor that has already passed it, and
        ``id > cursor`` never offers it again. Neither claim nor ledger stands behind a cursor to
        catch what the comparison skipped on its own.

        Time is what bounds it, and nothing else does: a fact still invisible belongs to a
        transaction still open, so once ``settled_before`` (:meth:`settled_before`) is passed no
        unseen key can be older than that. The cursor therefore stops at the last fact that old,
        and everything above it comes back on every tick until it settles — unbounded on purpose,
        so a burst larger than one batch is never left waiting behind its own cursor; the caller is
        what dedupes a replay (``spread``'s in-memory applied set, or the durable consumer's
        ``dispatched_consumers`` ledger), which is why offering it again costs nothing here.
        """
        found = list(
            await self.session.scalars(
                select(BusinessEventRecord)
                .where(BusinessEventRecord.id > cursor, BusinessEventRecord.kind.in_(kinds))
                .order_by(BusinessEventRecord.id)
            )
        )
        # The contiguous prefix: jumping past an unsettled fact could skip one surfacing below it.
        settled = list(takewhile(lambda record: record.created_at < settled_before, found))
        return found, settled[-1].id if settled else cursor

    async def already_consumed(self, topic: str, event_id: uuid.UUID | str) -> bool:
        """Record the delivery in the ``consumed_events`` ledger; ``True`` if it was already there.

        On the handler's session, so the mark commits or rolls back with the handler's writes.
        ``event_id`` may be a string, as replayed off the JSON queue."""
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
        """Newest first. RLS already limits rows to the reader's own and their orgs'; the filters
        narrow to one feed. ``text`` also searches the pinned names."""
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
                    BusinessEventRecord.entity_name.ilike(like),
                    BusinessEventRecord.user_name.ilike(like),
                    BusinessEventRecord.org_name.ilike(like),
                    BusinessEventRecord.request_name.ilike(like),
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
        """Per-day counts, RLS-scoped; days with none are absent."""
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
