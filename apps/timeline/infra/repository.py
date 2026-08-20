"""The merge reader — orchestrates the three stores behind the console Timeline into one list:
the business-events journal, issue occurrences and the firehose.

It never touches another context's tables: business events are read through the shared
``events.EventRepository`` (shared infra), the firehose through
``observability.firehose.read_firehose`` (shared infra too), issues through
``issues.contract.queries.search_issue_occurrences``.

All three now answer on the same session, which is what makes the ``logs`` source global rather
than whatever the instance serving the page happened to have on its own disk. Sorting and the cut
to the page size still happen in memory over the merged list: each source is asked for *its own*
newest rows, which is exact for the default time order and a sample for any other column — the
screen says so rather than imply otherwise.
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
from apps.shared.observability.models import LogLine
from apps.shared.observability.repository import LogRepository
from apps.timeline.domain.models import TimelineEntry, TimelineSource

_SORT_KEYS = {"ts", "source", "level", "org", "name", "user", "entity", "request"}

# The display level the viewer gives every business fact. Business events have no severity of their
# own — that is a logging notion — so this is the merged timeline's axis, never the journal's.
BUSINESS_LEVEL = "info"

# The activity chart's own lookback per grain — wider than the paginated table, so the graph can
# zoom out to a month without the timeline pulling a year of rows. Bounds match the fixed x-axis
# spans in ``router._GRAIN_SPAN``, and are skipped when the caller already set a date bound: a
# filter wins.
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
class TimelineFilter:
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

    def wants(self, source: TimelineSource) -> bool:
        """Whether this source can contribute given the source filter."""
        return self.source is None or self.source == source


def _app_of(logger: str) -> str:
    """The app a line belongs to, read off the logger that wrote it: the package under ``apps.``
    for our own code, the top-level distribution for a library's (``sqlalchemy.pool`` →
    ``sqlalchemy``). Reading it off the *event name* instead would guess, and guess wrong —
    ``invitation.accept_error`` belongs to organizations, ``page.provider_failed`` to shared.

    Shared by the firehose and by issue occurrences, which carry the logger in their captured
    context: a failure and the lines around it must land under the same app, or the pivot from an
    issue back to the code that raised it stops working."""
    head, _, rest = logger.partition(".")
    if head == "apps" and rest:
        return rest.partition(".")[0]
    return head


class TimelineReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, flt: TimelineFilter, *, limit: int = 100) -> list[TimelineEntry]:
        entries: list[TimelineEntry] = []
        # The firehose is level-gated at write time — what the level dropped was never
        # recorded — while the two sources below carry full history whatever the level.
        if flt.wants(TimelineSource.logs):
            rows = await LogRepository(self.session).search(**_log_kwargs(flt, limit))
            entries += [_from_log_line(r) for r in rows]
        # A business fact has no severity of its own — it is a domain event, not a log line. The
        # viewer needs one axis across its three sources, so it reads them all at BUSINESS_LEVEL;
        # a filter on any other level excludes the journal wholesale, as it does for issues.
        if flt.wants(TimelineSource.business) and flt.level in (None, BUSINESS_LEVEL):
            rows = await EventRepository(self.session).search(**_business_kwargs(flt, limit))
            entries += [_from_event(r) for r in rows]
        # Issue occurrences are always level "error"; a stricter level filter excludes them.
        if flt.wants(TimelineSource.issue) and flt.level in (None, "error"):
            rows = await search_issue_occurrences(self.session, **_issue_kwargs(flt, limit))
            entries += [_from_issue(r) for r in rows]
        # The app filter narrows the merged timeline to one app's event key prefix — applied in
        # memory over every source at once, the same seam sort/pagination already live in.
        if flt.app:
            entries = [e for e in entries if e.app == flt.app]
        # Correlating by the concerned entity keeps only its rows — which excludes the firehose and
        # issue sources outright, since neither carries an entity_id (only business events do).
        if flt.entity_id:
            entries = [e for e in entries if e.entity_id == flt.entity_id]
        return _sorted(entries, flt)[:limit]

    async def activity(
        self, flt: TimelineFilter, *, grain: str = "day", cap: int = 20000
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

    async def facets(
        self, flt: TimelineFilter, *, cap: int = 2000
    ) -> dict[str, list[dict[str, Any]]]:
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
            # Every source names an app — its own column, or the logger that wrote it — and the
            # filter runs over all three, so the pill has to offer all three. Counting business
            # rows alone left ``shared`` and every library filterable but never listed.
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
    """The human label for a request: its ``METHOD /path``.

    A business row carries it on its own ``request_name`` column, pinned when the request ran — so
    it stays legible long after the firehose window that produced the request has rolled over. A
    firehose line still derives it from its payload, where the request source binds both."""
    if entry.request_name:
        return entry.request_name
    method, path = entry.payload.get("method"), entry.payload.get("path")
    return f"{method} {path}" if method and path else None


def _request_facet(entries: list[TimelineEntry]) -> list[dict[str, Any]]:
    """Like ``_tally`` over ``request_id``, but each option also carries the request's route as its
    label so the pill reads ``GET /console/timeline`` instead of an opaque id (falling back to
    the id when no entry in the window describes the route)."""
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


def _event_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # The shared str base for all three sources: issue occurrences match a JSONB ``context ->>``
    # (text) and firehose lines match file JSON — both keep the ids as strings. Only the business
    # journal's uuid columns need parsing, done in ``_business_kwargs``.
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


def _business_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # The journal's id columns are uuid; TimelineFilter carries them as strings off the URL, so
    # parse at this boundary — a malformed id raises.
    kwargs = _event_kwargs(flt, limit)
    del kwargs["level"]  # the journal carries no level column — see BUSINESS_LEVEL
    kwargs["org_id"] = uuid.UUID(flt.org_id) if flt.org_id else None
    kwargs["user_id"] = uuid.UUID(flt.user_id) if flt.user_id else None
    kwargs["entity_id"] = uuid.UUID(flt.entity_id) if flt.entity_id else None
    kwargs["request_id"] = uuid.UUID(flt.request_id) if flt.request_id else None
    return kwargs


def _issue_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    kwargs = _event_kwargs(flt, limit)
    del kwargs["level"]  # issues carry no level column — always "error"
    del kwargs["entity_id"]  # issue occurrences aren't keyed to a domain entity
    return kwargs


def _log_kwargs(flt: TimelineFilter, limit: int) -> dict[str, Any]:
    # The firehose takes the same filters as the other two, minus entity_id — a log line is not
    # keyed to a domain entity (the merged list drops it in memory below).
    kwargs = _event_kwargs(flt, limit)
    del kwargs["entity_id"]
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
    # TimelineEntry merges three sources (firehose ids are plain strings from JSON), so its ids
    # stay str: stringify the journal record's uuids at this boundary.
    return TimelineEntry(
        ts=record.created_at,
        source=TimelineSource.business,
        level=BUSINESS_LEVEL,
        name=record.kind,
        app=record.app_name,  # its own column — never re-split out of the composed kind
        org_id=str(record.org_id) if record.org_id else None,
        user_id=str(record.user_id) if record.user_id else None,
        entity_id=str(record.entity_id) if record.entity_id else None,
        entity_name=record.entity_name,
        request_id=str(record.request_id) if record.request_id else None,
        request_name=record.request_name,
        payload=record.payload or {},
    )


def _from_issue(occurrence: IssueOccurrence) -> TimelineEntry:
    ctx = occurrence.context
    return TimelineEntry(
        ts=occurrence.ts,
        source=TimelineSource.issue,
        level="error",
        name=occurrence.title,
        # Never the title: it is ``ValueError: user 42 not found``, an exception type and a
        # message, so reading an app out of it yielded the whole title and no filter ever matched.
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
    # Secondary key on ts keeps ties deterministic (and chronological within a column sort).
    return sorted(entries, key=lambda e: (_sort_value(e, key), e.ts), reverse=flt.descending)
