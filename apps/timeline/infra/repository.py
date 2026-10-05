"""Merges the journal, issue occurrences and the log sink into the Timeline's one list
(AGENTS: the Timeline reads the journal, the log sink and the issues), each through its owner's
repository or contract.

Sort and page cut run in memory over the merged list, each source giving its own newest rows:
exact for newest-first, a sample for any other order, which the screen says.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.contract.queries import IssueOccurrence, search_issue_occurrences
from apps.shared import clock
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository import EventRepository
from apps.shared.logs.models import LogLine
from apps.shared.logs.repository import LogRepository
from apps.timeline.domain.models import Grain, TimelineEntry, TimelineSource

_SORT_KEYS = {"ts", "source", "level", "org", "name", "user", "entity", "request"}

# The level shown for a business fact, which has no severity of its own.
BUSINESS_LEVEL = "info"

# The activity chart's lookback per grain, matching ``router._GRAIN_SPAN``; a date filter wins.
_GRAIN_WINDOW: dict[Grain, timedelta] = {
    "hour": timedelta(hours=24),
    "day": timedelta(days=14),
    "week": timedelta(weeks=12),
    "month": timedelta(days=366),
}


def bucket_key(ts: datetime, grain: Grain) -> str:
    """The bucket ``ts`` falls in; for ``day``, the ISO date the drivers assert on."""
    if grain == "hour":
        return ts.strftime("%Y-%m-%d %H:00")
    if grain == "week":
        return ts.strftime("%G-W%V")  # ISO week: sorts chronologically
    if grain == "month":
        return ts.strftime("%Y-%m")
    return ts.date().isoformat()


@dataclass(frozen=True)
class TimelineFilter:
    """Filters and sort, shared by the timeline, the activity graph and the export."""

    source: str | None = None
    app: str | None = None
    level: str | None = None
    org_id: str | None = None
    user_id: str | None = None
    entity_id: str | None = None
    request_id: str | None = None
    text: str | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    # The paging cursor: the oldest row shown. A timestamp, the only key the three sources share.
    before_ts: datetime | None = None
    sort: str = "ts"
    descending: bool = True

    def wants(self, source: TimelineSource) -> bool:
        return self.source is None or self.source == source

    def is_narrowed(self) -> bool:
        """Whether the read names a subject (org, user, entity, request, text), which drops the log
        store's default lookback: the other sources have none, and last week's request would show
        its fact without its lines. ``source``, ``app`` and ``level`` only narrow the kind of row.
        """
        return any((self.org_id, self.user_id, self.entity_id, self.request_id, self.text))

    def orders_whole_window(self) -> bool:
        """Only newest-first; any other order sorts each source's newest rows."""
        return self.sort == "ts" and self.descending


def _app_of(logger: str) -> str:
    """The app from a logger name: the package under ``apps.``, else the library
    (``sqlalchemy.pool`` → ``sqlalchemy``). Not from the event name (``invitation.accept_error``
    belongs to organizations). Used for log lines and occurrences alike, so both land under one
    app."""
    head, _, rest = logger.partition(".")
    if head == "apps" and rest:
        return rest.partition(".")[0]
    return head


class TimelineReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, flt: TimelineFilter, *, limit: int = 100) -> list[TimelineEntry]:
        entries: list[TimelineEntry] = []
        if flt.wants(TimelineSource.logs):
            rows = await LogRepository(self.session).search(**_log_kwargs(flt, limit))
            entries += [_from_log_line(r) for r in rows]
        # Facts read as BUSINESS_LEVEL; another level filter excludes them.
        if flt.wants(TimelineSource.business) and flt.level in (None, BUSINESS_LEVEL):
            rows = await EventRepository(self.session).search(**_business_kwargs(flt, limit))
            entries += [_from_event(r) for r in rows]
        # Occurrences are always "error".
        if flt.wants(TimelineSource.issue) and flt.level in (None, "error"):
            rows = await search_issue_occurrences(self.session, **_issue_kwargs(flt, limit))
            entries += [_from_issue(r) for r in rows]
        if flt.app:
            entries = [e for e in entries if e.app == flt.app]
        # Only facts carry an entity_id.
        if flt.entity_id:
            entries = [e for e in entries if e.entity_id == flt.entity_id]
        # Strict, unlike ``to_dt``, or the last row shown would top the next page. Rows sharing
        # the cursor's exact microsecond are lost: rare, and better than a row shown twice.
        if flt.before_ts:
            entries = [e for e in entries if e.ts < flt.before_ts]
        return _sorted(entries, flt)[:limit]

    async def activity(
        self, flt: TimelineFilter, *, grain: Grain = "day", cap: int = 20000
    ) -> dict[str, dict[str, int]]:
        """Counts per bucket and source, under the timeline's filters, over the chart's own
        lookback for ``grain``."""
        chart_flt = flt
        if grain in _GRAIN_WINDOW and not flt.from_dt:
            chart_flt = replace(flt, from_dt=clock.now() - _GRAIN_WINDOW[grain])
        buckets: dict[str, dict[str, int]] = {}
        for e in await self.search(chart_flt, limit=cap):
            b = buckets.setdefault(bucket_key(e.ts, grain), {})
            b[e.source.value] = b.get(e.source.value, 0) + 1
        return buckets

    async def facets(
        self, flt: TimelineFilter, *, cap: int = 2000
    ) -> dict[str, list[dict[str, Any]]]:
        """Each filter pill's values and counts, under the date and text filters only, so every
        value stays offered as filters stack."""
        base = replace(
            flt, source=None, app=None, level=None, org_id=None, user_id=None, request_id=None
        )
        entries = await self.search(base, limit=cap)
        return {
            "source": _tally(entries, lambda e: e.source.value),
            "app": _tally(entries, lambda e: e.app),
            "level": _tally(entries, lambda e: e.level),
            "org": _tally(entries, lambda e: e.org_id),
            "user": _tally(entries, lambda e: e.user_id),
            "request": _request_facet(entries),
        }


def _tally(
    entries: list[TimelineEntry], pick: Callable[[TimelineEntry], str | None]
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for e in entries:
        value = pick(e)
        if value:
            counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": value, "count": count} for value, count in ranked]


def request_desc(entry: TimelineEntry) -> str | None:
    """``METHOD /path``: pinned on a fact, read from a log line's payload."""
    if entry.request_name:
        return entry.request_name
    method, path = entry.payload.get("method"), entry.payload.get("path")
    return f"{method} {path}" if method and path else None


def _request_facet(entries: list[TimelineEntry]) -> list[dict[str, Any]]:
    """``_tally`` over ``request_id``, labelled ``GET /console/timeline`` when known."""
    counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    for e in entries:
        rid = e.request_id
        if not rid:
            continue
        counts[rid] = counts.get(rid, 0) + 1
        if rid not in labels and (desc := request_desc(e)):
            labels[rid] = desc
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": rid, "count": count, "label": labels.get(rid, rid)} for rid, count in ranked]


def _upper_bound(flt: TimelineFilter) -> datetime | None:
    """The tighter of ``to_dt`` and the paging cursor."""
    bounds = [d for d in (flt.to_dt, flt.before_ts) if d is not None]
    return min(bounds) if bounds else None


def _event_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # Ids stay strings, as occurrences and log lines store them; ``_business_kwargs`` parses
    # them. The cursor rides on ``to_dt``; its strictness is applied in ``search``.
    return {
        "level": flt.level,
        "org_id": flt.org_id,
        "user_id": flt.user_id,
        "entity_id": flt.entity_id,
        "request_id": flt.request_id,
        "text": flt.text,
        "from_dt": flt.from_dt,
        "to_dt": _upper_bound(flt),
        "limit": limit,
    }


def _business_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # A malformed id raises.
    kwargs = _event_kwargs(flt, limit)
    del kwargs["level"]
    kwargs["org_id"] = uuid.UUID(flt.org_id) if flt.org_id else None
    kwargs["user_id"] = uuid.UUID(flt.user_id) if flt.user_id else None
    kwargs["entity_id"] = uuid.UUID(flt.entity_id) if flt.entity_id else None
    kwargs["request_id"] = uuid.UUID(flt.request_id) if flt.request_id else None
    return kwargs


def _issue_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    kwargs = _event_kwargs(flt, limit)
    del kwargs["level"]
    del kwargs["entity_id"]
    return kwargs


def _log_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # A read naming a subject drops the default lookback (see ``is_narrowed``).
    kwargs = _event_kwargs(flt, limit)
    del kwargs["entity_id"]
    if flt.is_narrowed():
        kwargs["window"] = None
    return kwargs


def _from_log_line(line: LogLine) -> TimelineEntry:
    return TimelineEntry(
        ts=line.ts,
        source=TimelineSource.logs,
        level=line.level,
        name=line.name,
        app=_app_of(line.logger),
        org_id=line.org_id,
        user_id=line.user_id,
        request_id=line.request_id,
        payload=line.payload,
    )


def _from_event(record: BusinessEventRecord) -> TimelineEntry:
    return TimelineEntry(
        ts=record.created_at,
        source=TimelineSource.business,
        level=BUSINESS_LEVEL,
        name=record.kind,
        app=record.app_name,
        org_id=str(record.org_id) if record.org_id else None,
        org_name=record.org_name,
        user_id=str(record.user_id) if record.user_id else None,
        user_name=record.user_name,
        entity_id=str(record.entity_id) if record.entity_id else None,
        entity_name=record.entity_name,
        request_id=str(record.request_id) if record.request_id else None,
        request_name=record.request_name,
        payload=record.payload,
    )


def _from_issue(occurrence: IssueOccurrence) -> TimelineEntry:
    ctx = occurrence.context
    return TimelineEntry(
        ts=occurrence.ts,
        source=TimelineSource.issue,
        level="error",
        name=occurrence.title,
        # Not from the title, which is ``ValueError: user 42 not found``.
        app=_app_of(str(ctx.get("logger") or "")),
        org_id=ctx.get("org_id"),
        user_id=ctx.get("user_id"),
        request_id=ctx.get("request_id"),
        issue_id=str(occurrence.issue_id),
        payload=ctx,
    )


def _sort_value(entry: TimelineEntry, key: str) -> Any:
    if key == "ts":
        return entry.ts
    attr = {"org": "org_id", "user": "user_id", "entity": "entity_id", "request": "request_id"}.get(
        key, key
    )
    return getattr(entry, attr, "") or ""


def _sorted(entries: list[TimelineEntry], flt: TimelineFilter) -> list[TimelineEntry]:
    key = flt.sort if flt.sort in _SORT_KEYS else "ts"
    # ts breaks ties.
    return sorted(entries, key=lambda e: (_sort_value(e, key), e.ts), reverse=flt.descending)
