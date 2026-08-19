"""The unified timeline entry — one envelope over three sources.

``apps/timeline`` is a pure reader: it writes nothing. It merges, at read time, the three
systems that record anything — the structlog firehose (a rotated JSON file), the business-events
journal (``business_events``) and issue occurrences (``issue_occurrences``) — into this single
shape, keyed for correlation by ``request_id`` / ``org_id`` / ``user_id`` / ``entity_id`` (the
concerned entity).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from apps.shared.vocabulary import AppName


class TimelineSource(StrEnum):
    logs = "logs"  # the structlog firehose — requests, background work, libraries alike
    business = "business"  # the append-only business-events journal
    issue = "issue"  # occurrences of tracked issues


class TimelineEntry(BaseModel):
    """One entry of the unified timeline (a DTO, never an ORM row).

    ``name`` is what its source calls it: a business ``kind``, a firehose trace name, or an issue
    title. One column, three vocabularies — the viewer names its sources, it never renames them.

    ``app`` is the per-app axis the console browses by. A business fact carries it as its own
    column; the other two read it off the *logger* that wrote them — the one an occurrence keeps in
    its captured context — so a failure and the lines around it land under the same app."""

    ts: datetime
    source: TimelineSource
    level: str
    name: str
    app: AppName = ""
    org_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = None
    # The subject's name as it read *then*, pinned on the fact by the write path. Only a business
    # fact has one: a log line and an occurrence are about a moment, not about a thing.
    entity_name: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile" — carried by the source, not resolved at read
    payload: dict[str, Any] = Field(default_factory=dict)
