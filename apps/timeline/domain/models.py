"""The unified timeline entry — one envelope over three sources.

``apps/timeline`` is a pure reader: it writes nothing. It merges, at read time, the structlog
firehose (a rotated JSON file), the business-events journal (``business_events``) and issue
occurrences (``issue_occurrences``) into this single shape, keyed for correlation by
``request_id`` / ``org_id`` / ``user_id`` / ``entity_id`` (the concerned entity).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from apps.shared.vocabulary import AppName


class TimelineSource(StrEnum):
    http = "http"  # per-request firehose lines (request.failed — dead links & 5xx)
    app = "app"  # non-request structlog lines (queue, background…)
    business = "business"  # the append-only business-events journal
    error = "error"  # occurrences of tracked errors


class TimelineEntry(BaseModel):
    """One entry of the unified timeline (a DTO, never an ORM row).

    ``name`` is what its source calls it: a business ``kind``, a firehose trace name, or an issue
    title. One column, three vocabularies — the viewer names its sources, it never renames them.

    ``app`` is the per-app axis the console browses by. A business fact carries it as its own
    column; the other two sources have none, so they name themselves off their dotted name at the
    boundary that builds them."""

    ts: datetime
    source: TimelineSource
    level: str
    name: str
    app: AppName = ""
    org_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile" — carried by the source, not resolved at read
    payload: dict[str, Any] = Field(default_factory=dict)
