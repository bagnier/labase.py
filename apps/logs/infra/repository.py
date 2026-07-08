"""The merge reader — orchestrates the durable DB sources (audit trail + issue occurrences)
and (added in a later step) the firehose file into one timeline, applies sorting, and
paginates over a bounded recent window.

It never touches another context's tables: audit is read through
``shared.observability.search_audit_logs`` (audit is shared infra), issues through
``issues.contract.queries.search_issue_events``. Sorting/pagination happen in memory over the
merged window — the only way to order a file stream and two tables as one timeline.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from apps.issues.contract.queries import IssueEventRow, search_issue_events
from apps.logs.domain.models import LogEntry, LogSource
from apps.shared.observability.audit import AuditRow, search_audit_logs

_SORT_KEYS = {"ts", "source", "level", "org", "event", "user", "request"}


@dataclass(frozen=True)
class LogFilter:
    """The seven combinable filters (all optional) plus sort — the read contract shared by
    the timeline, the activity graph and the export."""

    source: str | None = None
    level: str | None = None
    org_id: str | None = None
    user_id: str | None = None
    request_id: str | None = None
    text: str | None = None
    from_dt: datetime | None = None
    to_dt: datetime | None = None
    sort: str = "ts"
    descending: bool = True

    def wants(self, source: LogSource) -> bool:
        """Whether this source can contribute given the source filter."""
        return self.source is None or self.source == source


class LogReader:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def search(self, flt: LogFilter, *, limit: int = 100) -> list[LogEntry]:
        entries: list[LogEntry] = []
        if flt.wants(LogSource.audit):
            rows = await search_audit_logs(self.session, **_audit_kwargs(flt, limit))
            entries += [_from_audit(r) for r in rows]
        # Issue occurrences are always level "error"; a stricter level filter excludes them.
        if flt.wants(LogSource.issue) and flt.level in (None, "error"):
            rows = await search_issue_events(self.session, **_issue_kwargs(flt, limit))
            entries += [_from_issue(r) for r in rows]
        return _sorted(entries, flt)[:limit]

    async def activity(self, flt: LogFilter, *, cap: int = 5000) -> dict[str, dict[str, int]]:
        """Per-day, per-source counts over the filtered window — feeds the stacked graph.
        Honours the same filters as the timeline (see the two activity scenarios)."""
        buckets: dict[str, dict[str, int]] = {}
        for e in await self.search(flt, limit=cap):
            day = buckets.setdefault(e.ts.date().isoformat(), {})
            day[e.source.value] = day.get(e.source.value, 0) + 1
        return buckets


def _audit_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    return {
        "level": flt.level,
        "org_id": flt.org_id,
        "user_id": flt.user_id,
        "request_id": flt.request_id,
        "text": flt.text,
        "from_dt": flt.from_dt,
        "to_dt": flt.to_dt,
        "limit": limit,
    }


def _issue_kwargs(flt: LogFilter, limit: int) -> dict[str, Any]:
    kwargs = _audit_kwargs(flt, limit)
    del kwargs["level"]  # issues carry no level column — always "error"
    return kwargs


def _from_audit(row: AuditRow) -> LogEntry:
    return LogEntry(
        ts=row.ts,
        source=LogSource.audit,
        level=row.level,
        event=row.event,
        org_id=row.org_id,
        user_id=row.user_id,
        request_id=row.request_id,
        payload=row.payload,
    )


def _from_issue(row: IssueEventRow) -> LogEntry:
    ctx = row.context
    return LogEntry(
        ts=row.ts,
        source=LogSource.issue,
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
    attr = {"org": "org_id", "user": "user_id", "request": "request_id"}.get(key, key)
    return getattr(entry, attr, "") or ""


def _sorted(entries: list[LogEntry], flt: LogFilter) -> list[LogEntry]:
    key = flt.sort if flt.sort in _SORT_KEYS else "ts"
    # Secondary key on ts keeps ties deterministic (and chronological within a column sort).
    return sorted(entries, key=lambda e: (_sort_value(e, key), e.ts), reverse=flt.descending)
