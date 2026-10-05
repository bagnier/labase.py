"""The ORM mapping of ``log_lines``. Not ``LogLineRecord``: here a *record* is a business fact,
and a trace is not one.
"""

from typing import Any

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, UUIDPk


class LogLine(Base, UUIDPk):
    """One structlog line, flattened to the columns the Timeline filters on.

    ``ts`` is when the line was written, not when its batch was drained.

    The correlation keys are ``text``, unlike the journal's ``uuid``: they come from contextvars,
    where anything may be bound, and a value that does not parse must not cost the line.
    """

    __tablename__ = "log_lines"

    # Also part of the primary key: the table is partitioned by range on `ts`, and Postgres
    # requires the partition column in every unique key — `id` alone cannot be the key `(id, ts)`
    # the migration declares.
    ts: Mapped[Any] = mapped_column(DateTime(timezone=True), primary_key=True)
    level: Mapped[str]
    # The Timeline's app axis.
    logger: Mapped[str]
    # structlog's ``event``, renamed to avoid quoting it in every query.
    name: Mapped[str]
    org_id: Mapped[str | None] = mapped_column(Text, default=None)
    user_id: Mapped[str | None] = mapped_column(Text, default=None)
    request_id: Mapped[str | None] = mapped_column(Text, default=None)
    # Tells a single-instance outage from a global one.
    instance: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
