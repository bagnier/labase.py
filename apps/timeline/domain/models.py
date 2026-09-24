"""The unified timeline entry — one envelope over three sources.

``apps/timeline`` is a pure reader: it writes nothing. It merges, at read time, the three
systems that record anything — the log sink (one shared Postgres table), the business-events
journal (``business_events``) and issue occurrences (``issue_occurrences``) — into this single
shape, keyed for correlation by ``request_id`` / ``org_id`` / ``user_id`` / ``entity_id`` (the
concerned entity).
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from apps.shared.settings.live import SettingRow
from apps.shared.vocabulary import AppName

# The activity chart's bucket size — narrowed once at the router (from a query param) and carried
# as this type from there through the repository, so a wrong value is a type error rather than a
# silent fall-through to ``day`` or a ``KeyError`` past the one place that checked.
Grain = Literal["hour", "day", "week", "month"]


class TimelineSource(StrEnum):
    logs = "logs"  # the log sink — requests, background work, libraries alike
    business = "business"  # the append-only business-events journal
    issue = "issue"  # occurrences of tracked issues


class TimelineEntry(BaseModel):
    """One entry of the unified timeline (a DTO, never an ORM row).

    ``name`` is what its source calls it: a business ``kind``, a log trace name, or an issue
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
    # The actor's handle and the org's name as they read *then*, pinned on the fact by the write
    # path. Only a business fact has one: a log line and an occurrence carry the bare id, resolved
    # live by the viewer — which is what a closed account or a renamed/deleted org leaves behind.
    org_name: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    entity_id: str | None = None
    # The subject's name as it read *then*, pinned on the fact by the write path. Only a business
    # fact has one: a log line and an occurrence are about a moment, not about a thing.
    entity_name: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile" — carried by the source, not resolved at read
    # The issue an ``issue`` row is an occurrence of — its deep link. Only that source has one:
    # a fact and a log line are not sightings of anything.
    issue_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TimelinePage(BaseModel):
    """The console Timeline screen: the rows, the activity chart, the filter facets, the app's
    own settings, and the cursor to load older rows."""

    app: str
    entries: list[TimelineEntry]
    activity: dict[str, Any]
    facets: dict[str, Any]
    settings: list[SettingRow]
    next_before: str | None
