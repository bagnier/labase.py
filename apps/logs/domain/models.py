"""The unified log record — one envelope over three sources.

``apps/logs`` is a pure reader: it never writes logs. It merges, at read time, the
structlog firehose (a rotated JSON file), the business-events trail (``business_events``)
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
    business = "business"  # the append-only business-events trail
    error = "error"  # occurrences of tracked errors


class LogEntry(BaseModel):
    """A single line of the unified timeline (a DTO, never an ORM row)."""

    ts: datetime
    source: LogSource
    level: str
    event: str
    org_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile" — carried by the row, not resolved at read
    payload: dict[str, Any] = Field(default_factory=dict)
