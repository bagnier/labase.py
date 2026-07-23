"""The business-events repository — the one owner of ``business_events`` SQL.

Every read and write of the append-only trail goes through here: the emit write path
(:mod:`apps.shared.events.store`) persists a fact via :meth:`EventRepository.save`, the event
listener (:mod:`apps.shared.events.listener`) claims/marks/scans facts off it, and the
observability timeline reads it via :meth:`EventRepository.search`. Keeping the SQL in one place
lets the callers stay orchestration-only — no raw ``text(...)`` scattered across the subsystem.

The repository is bound to one :class:`AsyncSession`: RLS scopes reads to that session's reader
(members see their own and their orgs' rows; the admin session sees all), and writes ride the
session's transaction so a fact commits iff its action does.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import BigInteger, Date, DateTime, Text, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared import clock
from apps.shared.persistence.base import Base


class BusinessEventLog(Base):
    """The append-only business-event row. Members read their own/their orgs' rows via RLS;
    only the persister's BYPASSRLS admin session writes (no insert grant to authenticated)."""

    __tablename__ = "business_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    level: Mapped[str]
    kind: Mapped[str]
    icon: Mapped[str | None] = mapped_column(default=None)
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    entity_id: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)


@dataclass(frozen=True)
class BusinessEventRow:
    """A read of the business-events trail, flattened for the unified timeline."""

    ts: datetime
    level: str
    kind: str
    icon: str | None
    org_id: str | None
    user_id: str | None
    entity_id: str | None
    request_id: str | None
    payload: dict[str, Any]


# Claim a batch of never-dispatched facts, oldest first, skipping rows another listener holds.
_CLAIM = text(
    "SELECT id, kind, level, icon, user_id, org_id, entity_id, payload "
    "FROM business_events "
    "WHERE dispatched_at IS NULL "
    "ORDER BY id "
    "FOR UPDATE SKIP LOCKED "
    "LIMIT :batch"
)

# Read facts newer than a process's spread cursor whose kind has a ``spread`` subscriber. Unlike
# the claim above there is NO lock and NO ``dispatched_at`` — a ``spread`` handler must run on
# *every* instance (config reload), so each process keeps its own in-memory cursor.
_SPREAD_SCAN = text(
    "SELECT id, kind, user_id, org_id, entity_id, payload "
    "FROM business_events "
    "WHERE id > :cursor AND kind = ANY(:kinds) "
    "ORDER BY id"
)


class EventRepository:
    """All ``business_events`` SQL, bound to one session (RLS-scoped for reads; the write rides
    the session's transaction)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Write path (emit) ────────────────────────────────────────────────────────────────────

    async def save(
        self,
        *,
        kind: str,
        level: str,
        icon: str | None,
        user_id: str | None,
        ip: str | None,
        org_id: str | None,
        entity_id: str | None,
        request_id: str | None,
        payload: dict[str, Any] | None,
    ) -> None:
        """Add one row and flush it — the flush surfaces RLS/constraint errors now, within the
        caller's transaction; the caller commits."""
        self._session.add(
            BusinessEventLog(
                kind=kind,
                level=level,
                icon=icon,
                user_id=uuid.UUID(user_id) if user_id else None,
                ip=ip,
                org_id=uuid.UUID(org_id) if org_id else None,
                entity_id=entity_id,
                request_id=request_id,
                payload=payload or None,
            )
        )
        await self._session.flush()

    async def actor_handle(self, user_id: str | None) -> str | None:
        """Resolve the actor's handle, to denormalize into the event so the feed can show *who*
        acted. Runs on the persister's admin session: profiles are ``own read`` under RLS, so a
        member could never resolve a co-member at read time — storing it at write time keeps 'who'
        visible to every viewer, and pins the handle the actor bore at the moment of the action."""
        if not user_id:
            return None
        try:
            return await self._session.scalar(
                text("select handle from profiles where auth_user_id = :id"),
                {"id": uuid.UUID(user_id)},  # bind as uuid, not text, so the column compare holds
            )
        except Exception:
            return None

    # ── Delivery scans (the listener) ────────────────────────────────────────────────────────

    async def claim_undispatched(self, batch: int) -> list[dict[str, Any]]:
        """Claim a batch of never-dispatched facts (``FOR UPDATE SKIP LOCKED``), oldest first —
        N instances never double-claim a row. The caller marks them dispatched in the same
        transaction."""
        result = await self._session.execute(_CLAIM, {"batch": batch})
        return [dict(r) for r in result.mappings()]

    async def mark_dispatched(self, ids: list[int]) -> None:
        """Stamp ``dispatched_at`` on the claimed rows — commits with their enqueued tasks."""
        await self._session.execute(
            text("UPDATE business_events SET dispatched_at = now() WHERE id = ANY(:ids)"),
            {"ids": ids},
        )

    async def scan_spread(self, cursor: int, kinds: list[str]) -> list[dict[str, Any]]:
        """Facts newer than ``cursor`` whose kind is in ``kinds`` — no lock, no dispatch mark:
        every instance replays its own ``spread`` subscribers off its own cursor."""
        result = await self._session.execute(_SPREAD_SCAN, {"cursor": cursor, "kinds": kinds})
        return [dict(r) for r in result.mappings()]

    # ── Read path (observability timeline, dashboards) ───────────────────────────────────────

    async def search(
        self,
        *,
        level: str | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
        entity_id: str | None = None,
        request_id: str | None = None,
        app: str | None = None,
        text: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[BusinessEventRow]:
        """Newest-first, bounded read of the trail under the given filters.

        RLS scopes the rows to the session's reader (self + org memberships); admin sessions see
        all. Callers still pass ``user_id=`` / ``org_id=`` to narrow to one feed. ``app`` matches
        the ``kind`` prefix (``"todo"`` → ``todo.*``); ``offset`` pages a fixed ``limit`` window."""
        query = (
            select(BusinessEventLog)
            .order_by(BusinessEventLog.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if level:
            query = query.where(BusinessEventLog.level == level)
        if org_id:
            query = query.where(BusinessEventLog.org_id == uuid.UUID(org_id))
        if user_id:
            query = query.where(BusinessEventLog.user_id == uuid.UUID(user_id))
        if entity_id:
            query = query.where(BusinessEventLog.entity_id == entity_id)
        if request_id:
            query = query.where(BusinessEventLog.request_id == request_id)
        if app:
            query = query.where(BusinessEventLog.kind.like(f"{app}.%"))
        if text:
            like = f"%{text}%"
            query = query.where(
                or_(
                    BusinessEventLog.kind.ilike(like),
                    cast(BusinessEventLog.payload, Text).ilike(like),
                )
            )
        if from_dt:
            query = query.where(BusinessEventLog.created_at >= from_dt)
        if to_dt:
            query = query.where(BusinessEventLog.created_at <= to_dt)
        rows = await self._session.scalars(query)
        return [
            BusinessEventRow(
                ts=r.created_at,
                level=r.level,
                kind=r.kind,
                icon=r.icon,
                org_id=str(r.org_id) if r.org_id else None,
                user_id=str(r.user_id) if r.user_id else None,
                entity_id=r.entity_id,
                request_id=r.request_id,
                payload=r.payload or {},
            )
            for r in rows
        ]

    async def daily_counts(
        self,
        *,
        user_id: str | None = None,
        org_id: str | None = None,
        days: int = 366,
    ) -> dict[date, int]:
        """Per-day counts of the trail over a trailing window, for the contribution calendar.

        RLS-scoped like :meth:`search`; callers narrow to one feed with ``user_id`` / ``org_id``.
        Grouped by calendar day (DB timezone). Missing days simply don't appear — the calendar
        builder fills the gaps."""
        since = clock.now() - timedelta(days=days)
        day = cast(BusinessEventLog.created_at, Date)
        query = select(day, func.count()).where(BusinessEventLog.created_at >= since).group_by(day)
        if user_id:
            query = query.where(BusinessEventLog.user_id == uuid.UUID(user_id))
        if org_id:
            query = query.where(BusinessEventLog.org_id == uuid.UUID(org_id))
        rows = await self._session.execute(query)
        return {d: n for d, n in rows.all()}
