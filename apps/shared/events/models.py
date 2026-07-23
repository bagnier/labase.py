"""The shape of a business event on the trail.

One data structure, no behaviour: :class:`BusinessEventLog` is the ORM mapping of the append-only
``business_events`` table — the single shape written on ``emit`` *and* handed back on a read (the
session keeps ``expire_on_commit=False``, so a read row stays usable past its session). Access logic
— writing and querying it — lives in the repository; humanizing a row for a surface lives in
:mod:`apps.shared.events.timeline`.
"""

import uuid
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
