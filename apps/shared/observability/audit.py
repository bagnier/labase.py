"""Append-only audit trail for sensitive business actions.

Best-effort by doctrine (README): logged immediately, then persisted to ``audit_logs``
as a background task — a lost audit write never blocks or fails the mutation. The unified
logs viewer (``apps/logs``) reads this trail through :func:`search_audit_logs` — audit is
shared infra, so its read query lives here with its writer, not in a bounded context.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from fastapi import BackgroundTasks
from sqlalchemy import BigInteger, DateTime, Text, cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from structlog.contextvars import get_contextvars

from apps.shared import clock
from apps.shared.persistence.base import Base
from apps.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.audit")


class AuditLog(Base):
    """The append-only audit row. RLS-enabled with no policy — written and read only through
    the BYPASSRLS admin session (``admin_session_factory``)."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    level: Mapped[str]
    event: Mapped[str]
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    ip: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    request_id: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)


@dataclass(frozen=True)
class AuditRow:
    """A read of the audit trail, flattened for the unified timeline."""

    ts: datetime
    level: str
    event: str
    org_id: str | None
    user_id: str | None
    request_id: str | None
    payload: dict[str, Any]


async def search_audit_logs(
    session: AsyncSession,
    *,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    text: str | None = None,
    from_dt: datetime | None = None,
    to_dt: datetime | None = None,
    limit: int = 100,
) -> list[AuditRow]:
    """Newest-first, bounded read of the audit trail under the given filters."""
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if level:
        query = query.where(AuditLog.level == level)
    if org_id:
        query = query.where(AuditLog.org_id == uuid.UUID(org_id))
    if user_id:
        query = query.where(AuditLog.user_id == uuid.UUID(user_id))
    if request_id:
        query = query.where(AuditLog.request_id == request_id)
    if text:
        like = f"%{text}%"
        query = query.where(
            or_(AuditLog.event.ilike(like), cast(AuditLog.payload, Text).ilike(like))
        )
    if from_dt:
        query = query.where(AuditLog.created_at >= from_dt)
    if to_dt:
        query = query.where(AuditLog.created_at <= to_dt)
    rows = await session.scalars(query)
    return [
        AuditRow(
            ts=r.created_at,
            level=r.level,
            event=r.event,
            org_id=str(r.org_id) if r.org_id else None,
            user_id=str(r.user_id) if r.user_id else None,
            request_id=r.request_id,
            payload=r.payload or {},
        )
        for r in rows
    ]


async def _insert_audit_log(
    level: str,
    event: str,
    user_id: str | None,
    ip: str | None,
    org_id: str | None,
    request_id: str | None,
    payload: dict[str, Any],
) -> None:
    try:
        async with admin_session_factory()() as session:
            session.add(
                AuditLog(
                    level=level,
                    event=event,
                    user_id=uuid.UUID(user_id) if user_id else None,
                    ip=ip,
                    org_id=uuid.UUID(org_id) if org_id else None,
                    request_id=request_id,
                    payload=payload or None,
                )
            )
            await session.commit()
    except Exception:
        log.warning("audit.write_failed", event=event, user_id=user_id)


def _record_audit_event(
    bg: BackgroundTasks,
    *,
    level: str,
    event: str,
    user_id: str | None = None,
    ip: str | None = None,
    org_id: str | None = None,
    request_id: str | None = None,
    **payload: Any,
) -> None:
    log.info(event, level=level, user_id=user_id, ip=ip, org_id=org_id, **payload)
    bg.add_task(_insert_audit_log, level, event, user_id, ip, org_id, request_id, payload)


def audit(
    bg: BackgroundTasks,
    event: str,
    *,
    level: str = "info",
    user_id: str | uuid.UUID | None = None,
    org_id: str | uuid.UUID | None = None,
    ip: str | None = None,
    **fields: Any,
) -> None:
    """Record a sensitive action: logged now, persisted after the response via ``bg`` (the
    request's ``BackgroundTasks``), so the audit write never delays the mutation.

    ``org_id`` and the request's ``request_id`` (read from the structlog contextvars bound by
    ``RequestLogger``) are persisted as first-class columns — the unified logs viewer filters
    by org and correlates on request_id.
    """
    _record_audit_event(
        bg,
        level=level,
        event=event,
        user_id=str(user_id) if user_id is not None else None,
        ip=ip,
        org_id=str(org_id) if org_id is not None else None,
        request_id=get_contextvars().get("request_id"),
        **fields,
    )
