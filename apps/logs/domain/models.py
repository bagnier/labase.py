"""The unified log record — one envelope over three sources.

``apps/logs`` is a pure reader: it never writes logs. It merges, at read time, the
structlog firehose (a rotated JSON file), the business-events journal (``business_events``)
and issue occurrences (``error_events``) into this single shape, keyed for correlation by
``request_id`` / ``org_id`` / ``user_id`` / ``entity_id`` (the concerned entity).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LogSource(StrEnum):
    http = "http"  # per-request firehose lines (request.failed — dead links & 5xx)
    app = "app"  # non-request structlog lines (queue, background…)
    business = "business"  # the append-only business-events journal
    error = "error"  # occurrences of tracked errors


class LogEntry(BaseModel):
    """A single line of the unified timeline (a DTO, never an ORM row)."""

    ts: datetime
    source: LogSource
    level: str
    event: str
    # The owning app — the per-app axis the console browses by. A business row carries it as its
    # own column; the other two sources have no such column, so they name themselves from their
    # dotted event key at the boundary that builds them.
    app: str = ""
    org_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile" — carried by the row, not resolved at read
    payload: dict[str, Any] = Field(default_factory=dict)
