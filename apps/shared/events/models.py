"""The shapes of a business event on the way in and out of the trail.

Two data structures, no behaviour: :class:`BusinessEventLog` is the ORM mapping of the append-only
``business_events`` table (the write shape), :class:`BusinessEventRow` is the flattened DTO the
:class:`~apps.shared.events.repository.EventRepository` returns from a read (the read shape). Access
logic — writing and querying them — lives in the repository; humanizing a row for a surface lives in
:mod:`apps.shared.events.timeline`.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime
from sqlalchemy.dialects.postgresql import JSONB
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
