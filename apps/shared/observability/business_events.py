"""The business-events store — the append-only trail every domain event is persisted to.

The producer is the typed event bus (:mod:`apps.shared.events`): a single subscriber on the
:class:`~apps.shared.events.BusinessEvent` base records every emitted event here. The store is
member-readable (RLS scopes rows to the reader), so the profile and org-dashboard timelines
read it on the user's own session; the admin console reads it all through the BYPASSRLS session.

Best-effort by doctrine (README): the write is fire-and-forget so ``emit()`` never blocks on the
DB and a lost write never fails the mutation — exactly the semantics of the audit trail this
store grew out of. Presentation helpers (:func:`activity_entries`) render a scoped, payload-free
timeline; the raw ``kind``/payload never reach a member.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import BigInteger, DateTime, Text, cast, or_, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from structlog.contextvars import get_contextvars

from apps.shared import clock
from apps.shared.bus import _loggable_payload
from apps.shared.events import BusinessEvent
from apps.shared.persistence.base import Base
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.business_events")


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


async def search_business_events(
    session: AsyncSession,
    *,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
) -> list[BusinessEventRow]:
    """Newest-first, bounded read of the trail under the given filters.

    RLS scopes the rows to the session's reader (self + org memberships); admin sessions see
    all. Callers still pass ``user_id=`` / ``org_id=`` to narrow to one feed."""
    query = select(BusinessEventLog).order_by(BusinessEventLog.id.desc()).limit(limit)
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
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(BusinessEventLog.kind.ilike(like), cast(BusinessEventLog.payload, Text).ilike(like))
        )
    if from_dt:
        query = query.where(BusinessEventLog.created_at >= from_dt)
    if to_dt:
        query = query.where(BusinessEventLog.created_at <= to_dt)
    rows = await session.scalars(query)
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


async def _actor_handle(session: AsyncSession, user_id: str | None) -> str | None:
    """Resolve the actor's handle, to denormalize into the event so the feed can show *who* acted.
    Runs on the persister's admin session: profiles are ``own read`` under RLS, so a member could
    never resolve a co-member at read time — storing it at write time keeps 'who' visible to every
    viewer, and pins the handle the actor bore at the moment of the action."""
    if not user_id:
        return None
    try:
        return await session.scalar(
            text("select handle from profiles where auth_user_id = :id"),
            {"id": uuid.UUID(user_id)},  # bind as uuid, not text, so the column compare holds
        )
    except Exception:
        return None


async def insert_business_event(
    *,
    kind: str,
    level: str,
    icon: str | None = None,
    user_id: str | None,
    ip: str | None,
    org_id: str | None,
    entity_id: str | None = None,
    request_id: str | None,
    payload: dict[str, Any] | None,
) -> None:
    """Write one row on a fresh admin session. Swallows failures (best-effort trail)."""
    try:
        async with admin_session_factory()() as session:
            stored = dict(payload) if payload else {}
            handle = await _actor_handle(session, user_id)
            if handle:
                stored["actor"] = handle  # denormalized 'who' — RLS hides co-members' profiles
            session.add(
                BusinessEventLog(
                    kind=kind,
                    level=level,
                    icon=icon,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    ip=ip,
                    org_id=uuid.UUID(org_id) if org_id else None,
                    entity_id=entity_id,
                    request_id=request_id,
                    payload=stored or None,
                )
            )
            await session.commit()
    except Exception:
        log.warning("business_event.write_failed", kind=kind, user_id=user_id)


async def persist_business_event(event: BusinessEvent) -> None:
    """Bus subscriber on the ``BusinessEvent`` base: record every emitted event, non-blocking.

    Reads ``ip``/``request_id`` from the request contextvars *now*, then fire-and-forgets the
    write so ``emit()`` returns immediately — no DB round-trip on the mutation's critical path,
    and a failed write never fails the mutation."""
    ctx = get_contextvars()
    payload = _loggable_payload(event)
    payload.pop("actor_id", None)
    payload.pop("org_id", None)
    payload.pop("entity_id", None)  # promoted to its own column, like actor_id/org_id
    asyncio.create_task(
        insert_business_event(
            kind=event.kind,
            level=event.level,
            icon=event.icon,
            user_id=event.actor_id,
            ip=ctx.get("ip"),
            org_id=event.org_id,
            entity_id=event.entity_id,
            request_id=ctx.get("request_id"),
            payload=payload or None,
        )
    )


# ── Presentation — humanize rows for the profile/dashboard timeline ──────────────────────────

_FALLBACK_ICON = "circle"  # for legacy rows written before events carried an icon


def activity_label(kind: str) -> str:
    """`auth.oauth_signed_in` → `Oauth signed in` — readable without a per-event table. Purely
    string-shaping: shared never enumerates the apps, it just humanizes whatever kind it's given."""
    return kind.split(".", 1)[-1].replace("_", " ").capitalize()


def _ago(ts: datetime, now: datetime) -> str:
    """A compact relative moment (`3h ago`, `2d ago`, `Mar 4`) — an activity feed reads better in
    elapsed time than in wall-clock; the exact instant stays on the row's ``title``/``datetime``."""
    secs = max(0.0, (now - ts).total_seconds())
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 604800:
        return f"{int(secs // 86400)}d ago"
    return ts.strftime("%b %-d")


def activity_entries(
    rows: list[BusinessEventRow],
    *,
    show_actor: bool = True,
    link: Callable[[BusinessEventRow], str | None] | None = None,
) -> list[dict[str, Any]]:
    """Humanize rows for the activity feed — *who did what to which document, when*:

    - ``who``    the actor's handle (denormalized into the payload at write time); dropped when
                 ``show_actor`` is off, as on the profile's own trail where it's always the viewer.
    - ``label``  the verb (``created``/``ticked``/``member joined``…), humanized from the kind.
    - ``detail`` the object's own name (the todo title, the page, the file) — the *which*.
    - ``icon`` / ``level``  the event's phosphor glyph and severity (colours the node).
    - ``ts`` / ``ago``  the absolute instant (for ``time``) and a compact relative moment.
    - ``href``   an optional deep link the surface supplies via ``link`` (the entity's page, the
                 filtered logs…) — the timeline renders the row as a link when present.

    Never the raw ``kind`` or the rest of the payload — only these projected, safe fields."""
    now = clock.now()
    entries = []
    for r in rows:
        payload = r.payload or {}
        entries.append(
            {
                "who": payload.get("actor") if show_actor else None,
                "label": activity_label(r.kind),
                "detail": payload.get("label"),
                "icon": r.icon or _FALLBACK_ICON,
                "level": r.level,
                "ts": r.ts,
                "ago": _ago(r.ts, now),
                "href": link(r) if link else None,
            }
        )
    return entries
