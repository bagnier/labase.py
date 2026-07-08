"""The unified log record — one envelope over three sources.

``apps/logs`` is a pure reader: it never writes logs. It merges, at read time, the
structlog firehose (a rotated JSON file), the audit trail (``audit_logs``) and issue
occurrences (``error_events``) into this single shape, keyed for correlation by
``request_id`` / ``org_id`` / ``user_id``.
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class LogSource(StrEnum):
    request = "request"  # per-request firehose lines (request.started/finished)
    app = "app"  # non-request structlog lines (queue, events…)
    audit = "audit"  # the append-only audit trail
    issue = "issue"  # occurrences of tracked errors


class LogEntry(BaseModel):
    """A single line of the unified timeline (a DTO, never an ORM row)."""

    ts: datetime
    source: LogSource
    level: str
    event: str
    org_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
