"""The merge reader — orchestrates the durable DB sources (business-events trail + issue
occurrences) and (added in a later step) the firehose file into one timeline, applies sorting,
and paginates over a bounded recent window.

It never touches another context's tables: business events are read through the shared
``events.EventRepository`` (shared infra), issues through
``issues.contract.queries.search_issue_events``. Sorting/pagination happen in memory over the
merged window — the only way to order a file stream and two tables as one timeline.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.contract.queries import IssueEventRow, search_issue_events
from apps.logs.domain.models import LogEntry, LogSource
from apps.shared import clock
from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository import EventRepository
from apps.shared.observability.firehose import FirehoseRow, read_firehose

_SORT_KEYS = {"ts", "source", "level", "org", "event", "user", "entity", "request"}

# The activity chart's own lookback per grain — wider than the paginated table, so the graph can
# zoom out to a month without the timeline pulling a year of rows. Bounds match the fixed x-axis
# spans in ``router._GRAIN_SPAN``. Skipped when the caller already set a date bound (filter wins).
_GRAIN_WINDOW = {
    "hour": timedelta(hours=24),
    "day": timedelta(days=14),
    "week": timedelta(weeks=12),
    "month": timedelta(days=366),
}


def bucket_key(ts: datetime, grain: str) -> str:
    """The activity bucket a timestamp falls in, for the selected grain. ``day`` returns the ISO
    date (the machine-readable contract the drivers assert on); the others widen or narrow it."""
    if grain == "hour":
        return ts.strftime("%Y-%m-%d %H:00")
    if grain == "week":
        return ts.strftime("%G-W%V")  # ISO year + week, so weeks sort chronologically
    if grain == "month":
        return ts.strftime("%Y-%m")
    return ts.date().isoformat()


@dataclass(frozen=True)
class LogFilter:
    """The combinable filters (all optional) plus sort — the read contract shared by
    the timeline, the activity graph and the export."""

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
    sort: str = "ts"
    descending: bool = True

    def wants(self, source: LogSource) -> bool:
        """Whether this source can contribute given the source filter."""
        return self.source is None or self.source == source


def entry_app(entry: LogEntry) -> str:
    """The owning app of an entry — the first dotted segment of its event key (``todo.created``
    → ``todo``, ``request.failed`` → ``request``). Business events are ``<app>.<verb>``, so this
    is the per-app axis the console browses by; issues (bare titles) collapse to their full name."""
    return entry.event.split(".", 1)[0]


class LogReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, flt: LogFilter, *, limit: int = 100) -> list[LogEntry]:
        entries: list[LogEntry] = []
        # The firehose is a synchronous read of local files — the HTTP diagnostics stream
        # (request.failed), level-gated at write time; the durable sources below carry full history.
        if flt.wants(LogSource.http):
            entries += [_from_firehose(r) for r in read_firehose(**_firehose_kwargs(flt, limit))]
        if flt.wants(LogSource.business):
            rows = await EventRepository(self.session).search(**_business_kwargs(flt, limit))
            entries += [_from_event(r) for r in rows]
        # Issue occurrences are always level "error"; a stricter level filter excludes them.
        if flt.wants(LogSource.error) and flt.level in (None, "error"):
            rows = await search_issue_events(self.session, **_issue_kwargs(flt, limit))
            entries += [_from_issue(r) for r in rows]
        # The app filter narrows the merged timeline to one app's event key prefix — applied in
        # memory over every source at once, the same seam sort/pagination already live in.
        if flt.app:
            entries = [e for e in entries if entry_app(e) == flt.app]
        # Correlating by the concerned entity keeps only its rows — which excludes the firehose and
        # issue sources outright, since neither carries an entity_id (only business events do).
        if flt.entity_id:
            entries = [e for e in entries if e.entity_id == flt.entity_id]
        return _sorted(entries, flt)[:limit]

    async def activity(
        self, flt: LogFilter, *, grain: str = "day", cap: int = 20000
    ) -> dict[str, dict[str, int]]:
        """Per-bucket, per-source counts over the filtered window — feeds the stacked graph.
        Honours the same filters as the timeline (see the two activity scenarios); ``grain`` picks
        the bucket size (hour/day/week/month). Non-day grains widen the chart's own lookback so the
        graph can zoom out past the paginated table without dragging its window along."""
        chart_flt = flt
        if grain in _GRAIN_WINDOW and not flt.from_dt:
            chart_flt = replace(flt, from_dt=clock.now() - _GRAIN_WINDOW[grain])
        buckets: dict[str, dict[str, int]] = {}
        for e in await self.search(chart_flt, limit=cap):
            b = buckets.setdefault(bucket_key(e.ts, grain), {})
            b[e.source.value] = b.get(e.source.value, 0) + 1
        return buckets

    async def facets(self, flt: LogFilter, *, cap: int = 2000) -> dict[str, list[dict[str, Any]]]:
        """Distinct values with occurrence counts for the five categorical filters — the option
        lists behind the combobox pills. Honours only the date + text window (the categorical
        selections are cleared) so every pill offers all its pickable values and counts stay
        stable as an admin stacks filters — a discovery aid, not a live recount."""
        base = replace(
            flt, source=None, app=None, level=None, org_id=None, user_id=None, request_id=None
        )
        entries = await self.search(base, limit=cap)
        return {
            "source": _tally(entries, lambda e: e.source.value),
            # The app axis is a business notion (``<app>.<verb>``); only business rows have one.
            "app": _tally([e for e in entries if e.source == LogSource.business], entry_app),
            "level": _tally(entries, lambda e: e.level),
            "org": _tally(entries, lambda e: e.org_id),
            "user": _tally(entries, lambda e: e.user_id),
            "request": _request_facet(entries),
        }


def _tally(entries: list[LogEntry], pick: Callable[[LogEntry], str | None]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for e in entries:
        value = pick(e)
        if value:
            counts[value] = counts.get(value, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [{"value": value, "count": count} for value, count in ranked]


def request_desc(entry: LogEntry) -> str | None:
    """The human label for a request: its ``METHOD /path`` — the request source binds both onto
    every ``request.started/finished`` line's payload. Correlated event/issue rows carry neither,
    so a request only gets a label once one of its firehose lines is in the window."""
    method, path = entry.payload.get("method"), entry.payload.get("path")
    return f"{method} {path}" if method and path else None


def _request_facet(entries: list[LogEntry]) -> list[dict[str, Any]]:
    """Like ``_tally`` over ``request_id``, but each option also carries the request's route as its
    label so the pill reads ``GET /console/logs`` instead of an opaque id (falling back to the id
    when no line in the window describes the route)."""
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


def _event_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    # The shared str base for all three sources: issue occurrences match a JSONB ``context ->>``
    # (text) and firehose lines match file JSON — both keep the ids as strings. Only the business
    # trail's uuid columns need parsing, done in ``_business_kwargs``.
    return {
        "level": flt.level,
        "org_id": flt.org_id,
        "user_id": flt.user_id,
        "entity_id": flt.entity_id,
        "request_id": flt.request_id,
        "text": flt.text,
        "from_dt": flt.from_dt,
        "to_dt": flt.to_dt,
        "limit": limit,
    }


def _business_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    # The trail's id columns are uuid; LogFilter carries them as strings from the URL query, so
    # parse at this boundary (a malformed id raises, as the previous in-repository cast did).
    kwargs = _event_kwargs(flt, limit)
    kwargs["org_id"] = uuid.UUID(flt.org_id) if flt.org_id else None
    kwargs["user_id"] = uuid.UUID(flt.user_id) if flt.user_id else None
    return kwargs


def _issue_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    kwargs = _event_kwargs(flt, limit)
    del kwargs["level"]  # issues carry no level column — always "error"
    del kwargs["entity_id"]  # issue occurrences aren't keyed to a domain entity
    return kwargs


def _firehose_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    # The firehose keeps its own retention window; it takes the same filters as the DB sources,
    # minus entity_id — firehose lines aren't keyed to a domain entity (dropped in memory below).
    kwargs = _event_kwargs(flt, limit)
    del kwargs["entity_id"]
    return kwargs


def _from_firehose(row: FirehoseRow) -> LogEntry:
    return LogEntry(
        ts=row.ts,
        source=LogSource.http,
        level=row.level,
        event=row.event,
        org_id=row.org_id,
        user_id=row.user_id,
        request_id=row.request_id,
        payload=row.payload,
    )


def _from_event(row: BusinessEventLog) -> LogEntry:
    # LogEntry merges three sources (firehose ids are plain strings from JSON), so its ids stay str:
    # stringify the trail row's uuids at this boundary.
    return LogEntry(
        ts=row.created_at,
        source=LogSource.business,
        level=row.level,
        event=row.kind,
        org_id=str(row.org_id) if row.org_id else None,
        user_id=str(row.user_id) if row.user_id else None,
        entity_id=row.entity_id,
        request_id=row.request_id,
        payload=row.payload or {},
    )


def _from_issue(row: IssueEventRow) -> LogEntry:
    ctx = row.context
    return LogEntry(
        ts=row.ts,
        source=LogSource.error,
        level="error",
        event=row.title,
        org_id=ctx.get("org_id"),
        user_id=ctx.get("user_id"),
        request_id=ctx.get("request_id"),
        payload=ctx,
    )


def _sort_value(entry: LogEntry, key: str) -> Any:
    if key == "ts":
        return entry.ts
    attr = {"org": "org_id", "user": "user_id", "entity": "entity_id", "request": "request_id"}.get(
        key, key
    )
    return getattr(entry, attr, "") or ""


def _sorted(entries: list[LogEntry], flt: LogFilter) -> list[LogEntry]:
    key = flt.sort if flt.sort in _SORT_KEYS else "ts"
    # Secondary key on ts keeps ties deterministic (and chronological within a column sort).
    return sorted(entries, key=lambda e: (_sort_value(e, key), e.ts), reverse=flt.descending)
