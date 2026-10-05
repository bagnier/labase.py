"""The ORM mapping of the append-only ``business_events`` journal.

Only the columns that are the fact are mapped. ``checked_at``, the listener's routability claim,
is queue mechanics and stays off the model; the repository reaches it, the per-topic cursors and
the ledgers in raw SQL.
"""

import uuid
from typing import Any

from sqlalchemy import Computed
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Created, UUIDPk


class BusinessEventRecord(Base, UUIDPk, Created):
    """A recorded fact. Members read their own and their orgs' facts under RLS; writes go through
    ``record_business_event`` (see ``_RECORD`` in the repository).

    ``id`` is time-ordered, so it is both the listener's cursor and the feeds' newest-first order.

    Each key comes with the readable name it had at write time: the journal outlives renamed or
    deleted subjects, and RLS hides a co-member's handle at read time. Every one is nullable: a
    system fact has no actor, a server-wide fact no org, work outside a request no request."""

    __tablename__ = "business_events"

    app_name: Mapped[str]
    verb: Mapped[str]
    kind: Mapped[str] = mapped_column(
        Computed("app_name || '.' || verb", persisted=True), nullable=False
    )
    icon: Mapped[str] = mapped_column(default="circle")
    user_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    user_name: Mapped[str | None] = mapped_column(default=None)
    org_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    org_name: Mapped[str | None] = mapped_column(default=None)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    entity_name: Mapped[str | None] = mapped_column(default=None)
    request_id: Mapped[uuid.UUID | None] = mapped_column(default=None)
    # "GET /profile": keeps the request readable after the log sink has dropped its lines.
    request_name: Mapped[str | None] = mapped_column(default=None)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
