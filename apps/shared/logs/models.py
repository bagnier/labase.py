"""The shape of a log line.

One data structure, no behaviour — the twin of :mod:`apps.shared.events.models` for the technical
side. :class:`LogLine` is the ORM mapping of ``log_lines``: what
:class:`~apps.shared.logs.repository.LogRepository` writes *and* what it hands back, the
way ``BusinessEventRecord`` is both on the journal side (sessions keep ``expire_on_commit=False``,
so a read row stays usable past its session).

Not ``LogLineRecord``: in this codebase a *record* is a recorded fact — ``record_business_event``,
``BusinessEventRecord`` — and a technical trace is precisely not one.
"""

from typing import Any

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, UUIDPk


class LogLine(Base, UUIDPk):
    """One structlog line, flattened to the columns the Timeline filters and correlates on.

    ``ts`` is when the caller wrote the line, never when the batch reached the table: the queue
    between the two is drained on an interval, and a reader correlating against a business fact
    needs the moment the code spoke.

    The three correlation keys are ``text`` and not ``uuid``, unlike the journal's. A line inherits
    them from contextvars, where any caller may have bound anything; refusing a value that does not
    parse would drop the line instead of recording it, which is the opposite of the job.
    """

    __tablename__ = "log_lines"

    ts: Mapped[Any] = mapped_column(DateTime(timezone=True))
    level: Mapped[str]
    # The logger that wrote it — the app axis the Timeline browses by.
    logger: Mapped[str]
    # structlog's own word for this is ``event``; that name is not usable as a column here without
    # quoting every read, so the column is ``name`` and the mapping happens at the boundary.
    name: Mapped[str]
    org_id: Mapped[str | None] = mapped_column(Text, default=None)
    user_id: Mapped[str | None] = mapped_column(Text, default=None)
    request_id: Mapped[str | None] = mapped_column(Text, default=None)
    # Which process wrote it: with one shared store and N instances, a line that cannot say where
    # it came from makes a single-instance outage look like a global one.
    instance: Mapped[str]
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
