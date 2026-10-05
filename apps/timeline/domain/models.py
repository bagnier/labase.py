"""The Timeline's entry, one shape over its three sources."""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field

from apps.shared.settings.live import SettingRow
from apps.shared.vocabulary import AppName

# The activity chart's bucket size, narrowed once at the router.
Grain = Literal["hour", "day", "week", "month"]


class TimelineSource(StrEnum):
    logs = "logs"
    business = "business"
    issue = "issue"


class TimelineEntry(BaseModel):
    """One Timeline row. ``name`` is the source's own: a ``kind``, a log name or an issue title.
    ``app`` is a fact's column, else read off the logger."""

    ts: datetime
    source: TimelineSource
    level: str
    name: str
    app: AppName = ""
    org_id: str | None = None
    # Pinned on a fact at write time; other rows carry bare ids, resolved live.
    org_name: str | None = None
    user_id: str | None = None
    user_name: str | None = None
    entity_id: str | None = None
    # Facts only.
    entity_name: str | None = None
    request_id: str | None = None
    request_name: str | None = None  # "GET /profile"
    # ``issue`` rows only: the issue to link to.
    issue_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TimelinePage(BaseModel):
    app: str
    entries: list[TimelineEntry]
    activity: dict[str, Any]
    facets: dict[str, Any]
    settings: list[SettingRow]
    next_before: str | None
