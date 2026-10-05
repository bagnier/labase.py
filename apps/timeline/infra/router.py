import csv
import io
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, ClassVar, get_args
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.admin import resolve_user_emails
from apps.auth.contract.current import CurrentAdmin
from apps.organizations.contract.queries import org_handles
from apps.shared import clock
from apps.shared.charts import chart_config
from apps.shared.http import is_htmx, json_and_html, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.logs.repository import DEFAULT_WINDOW
from apps.shared.persistence.database import AdminSession
from apps.shared.settings.live import SettingRow, get_settings
from apps.timeline.domain.models import Grain, TimelineEntry, TimelinePage
from apps.timeline.infra.repository import TimelineFilter, TimelineReader, request_desc

router = APIRouter(tags=["timeline"])

_TIMELINE_APP = "timeline"
_LOG_LEVEL_KEY = "log_level"
# Rows per read; a full page suggests more below.
_PAGE_SIZE = 100


def _settings_rows() -> list[SettingRow]:
    return get_settings(_TIMELINE_APP).rows()


_GRAINS: tuple[Grain, ...] = get_args(Grain)
# ``(source, series label)``; colours match the template's legend, so the chart's own is off.
_SOURCE_SERIES = (("logs", "Logs"), ("business", "Business"), ("issue", "Issue"))

# Buckets on the x-axis per grain, ending now, so its width is stable. Matches
# ``repository._GRAIN_WINDOW``.
_GRAIN_SPAN: dict[Grain, int] = {"hour": 24, "day": 14, "week": 12, "month": 12}


def _bucket_label(key: str, grain: Grain) -> str:
    if grain == "hour":
        return key[11:16]  # HH:00
    if grain == "week":
        return key.split("-", 1)[1]  # W##
    if grain == "month":
        return key  # YYYY-MM
    return key[5:]  # MM-DD (day)


def _axis_keys(grain: Grain, now: datetime) -> list[str]:
    """The x-axis bucket keys, ending at the current period; empty buckets stay as zeros."""
    n = _GRAIN_SPAN[grain]
    ago = range(n - 1, -1, -1)  # oldest first
    if grain == "hour":
        base = now.replace(minute=0, second=0, microsecond=0)
        return [(base - timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in ago]
    if grain == "week":
        monday = now.date() - timedelta(days=now.weekday())
        return [(monday - timedelta(weeks=i)).strftime("%G-W%V") for i in ago]
    if grain == "month":
        y, m, seq = now.year, now.month, []
        for _ in range(n):
            seq.append(f"{y:04d}-{m:02d}")
            y, m = (y - 1, 12) if m == 1 else (y, m - 1)
        return list(reversed(seq))
    base = now.date()  # day
    return [(base - timedelta(days=i)).isoformat() for i in ago]


def _activity_chart(
    activity: dict[str, dict[str, int]], grain: Grain, now: datetime
) -> dict[str, Any]:
    keys = _axis_keys(grain, now)
    series = [
        {"name": label, "data": [activity.get(k, {}).get(source, 0) for k in keys]}
        for source, label in _SOURCE_SERIES
    ]
    return chart_config(
        "bar",
        series,
        colors=["info", "secondary", "error"],
        chart={"height": 200, "stacked": True},
        plotOptions={"bar": {"columnWidth": "65%"}},
        xaxis={
            "categories": [_bucket_label(k, grain) for k in keys],
            "tickAmount": 6,  # at most this many labels
            "axisTicks": {"show": False},
            "labels": {"rotate": 0, "hideOverlappingLabels": True},
        },
        yaxis={"min": 0, "forceNiceScale": True, "tickAmount": 4},
        grid={"padding": {"left": 8, "right": 8}},
        legend={"show": False},
    )


def _bound(value: str) -> datetime | None:
    """A ``datetime-local`` input or a bare date, as UTC; empty is no bound."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@dataclass(frozen=True)
class TimelineQuery:
    """The filter as the query string carries it: plain strings, empty meaning "not filtered"
    (a form field cannot be absent). :meth:`to_filter` turns it into :class:`TimelineFilter`.
    """

    source: str = ""
    app: str = ""
    level: str = ""
    org_id: str = ""
    user_id: str = ""
    entity_id: str = ""
    request_id: str = ""
    q: str = ""
    from_dt: str = ""
    to_dt: str = ""
    sort: str = "ts"
    dir: str = "desc"
    # The paging cursor: ISO timestamp of the oldest row shown.
    before: str = ""

    # View state, not filters: carried into an export, ``before`` would cut it at the current page.
    _ORDERING: ClassVar[tuple[str, ...]] = ("sort", "dir", "before")

    def to_filter(self) -> TimelineFilter:
        return TimelineFilter(
            source=self.source or None,
            app=self.app or None,
            level=self.level or None,
            org_id=self.org_id or None,
            user_id=self.user_id or None,
            entity_id=self.entity_id or None,
            request_id=self.request_id or None,
            text=self.q or None,
            from_dt=_bound(self.from_dt),
            to_dt=_bound(self.to_dt),
            before_ts=_bound(self.before),
            sort=self.sort or "ts",
            descending=(self.dir != "asc"),
        )

    def active(self) -> dict[str, str]:
        """The filters set, for sort, grain and export links."""
        return {
            f.name: value
            for f in fields(self)
            if f.name not in self._ORDERING and (value := getattr(self, f.name))
        }

    def query_string(self) -> str:
        return urlencode(self.active())


TimelineQueryParams = Annotated[TimelineQuery, Depends()]


def _short(value: str) -> str:
    return value[:8]


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _ids(
    facet: list[dict[str, Any]], entries: list[TimelineEntry], attr: str, selected: str | None
) -> set[str]:
    """Ids to label: facet options, visible rows, current selection."""
    values = {o["value"] for o in facet}
    values |= {v for e in entries if (v := getattr(e, attr))}
    if selected:
        values.add(selected)
    return values


async def _org_labeler(session: AdminSession, values: set[str]) -> Callable[[str], str]:
    """Org id → handle, in one lookup; unknown ids show short."""
    uuids = {_as_uuid(v) for v in values}
    handles = await org_handles(session, {i for i in uuids if i is not None})

    def label(value: str) -> str:
        oid = _as_uuid(value)
        return handles.get(oid, _short(value)) if oid else _short(value)

    return label


async def _user_labeler(values: set[str]) -> Callable[[str], str]:
    """User id → email, in one batch; unknown ids show short."""
    uuids = {_as_uuid(v) for v in values}
    emails = await resolve_user_emails([i for i in uuids if i is not None])

    def label(value: str) -> str:
        uid = _as_uuid(value)
        return (emails.get(uid) or _short(value)) if uid else _short(value)

    return label


def _request_routes(facet: list[dict[str, Any]], entries: list[TimelineEntry]) -> dict[str, str]:
    """Request id → route, from the facet and the visible rows."""
    routes = {o["value"]: o["label"] for o in facet}
    for e in entries:
        if e.request_id and (desc := request_desc(e)):
            routes[e.request_id] = desc
    return routes


def _next_cursor(entries: list[TimelineEntry], flt: TimelineFilter) -> str | None:
    """The cursor for the next page, or ``None``. Only newest-first: another order sorts a
    sample, and paging it would compound the sample. Offered on a full page, at the cost of a
    possible empty last click.
    """
    if len(entries) < _PAGE_SIZE or not flt.orders_whole_window():
        return None
    return entries[-1].ts.isoformat()


@router.get("", responses=json_and_html(TimelinePage))
async def timeline_screen(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    filters: TimelineQueryParams,
    bucket: str = "day",
) -> Response:
    flt = filters.to_filter()
    org_id, user_id, request_id = filters.org_id, filters.user_id, filters.request_id
    grain: Grain = bucket if bucket in _GRAINS else "day"
    reader = TimelineReader(session)
    entries = await reader.search(flt, limit=_PAGE_SIZE)
    activity = await reader.activity(flt, grain=grain)
    facets = await reader.facets(flt)

    org_of = await _org_labeler(session, _ids(facets["org"], entries, "org_id", org_id))
    user_of = await _user_labeler(_ids(facets["user"], entries, "user_id", user_id))
    routes = _request_routes(facets["request"], entries)
    for option in facets["org"]:
        option["label"] = org_of(option["value"])
    for option in facets["user"]:
        option["label"] = user_of(option["value"])

    org_label = org_of(org_id) if org_id else ""
    user_label = user_of(user_id) if user_id else ""
    request_label = (routes.get(request_id) or _short(request_id)) if request_id else ""
    row_labels = {
        "org": {e.org_id: org_of(e.org_id) for e in entries if e.org_id},
        "user": {e.user_id: user_of(e.user_id) for e in entries if e.user_id},
        "request": {
            e.request_id: routes.get(e.request_id) or _short(e.request_id)
            for e in entries
            if e.request_id
        },
    }
    settings = _settings_rows()
    next_before = _next_cursor(entries, flt)
    if wants_json(request):
        return JSONResponse(
            {
                "app": _TIMELINE_APP,
                "entries": [e.model_dump(mode="json") for e in entries],
                "activity": activity,
                "facets": facets,
                "settings": settings,
                "next_before": next_before,
            }
        )
    rows = {
        "entries": entries,
        "labels": row_labels,
        "next_before": next_before,
        "load_more_qs": filters.query_string(),
        "grain": grain,
    }
    # "Load older" swaps in rows only, and its own successor button.
    if is_htmx(request):
        return templates.TemplateResponse(request, "timeline/_entries.html", rows)
    return templates.TemplateResponse(
        request,
        "timeline/index.html",
        {
            **rows,
            "user": current_user,
            "activity": activity,
            "activity_chart": _activity_chart(activity, grain, clock.now()),
            "grains": _GRAINS,
            "facets": facets,
            "org_label": org_label,
            "user_label": user_label,
            "request_label": request_label,
            "settings": [r for r in settings if r["key"] == _LOG_LEVEL_KEY],
            "filters": filters,
            "sort": flt.sort,
            "dir": "desc" if flt.descending else "asc",
            "exact_order": flt.orders_whole_window(),
            # Only the logs have a window; the screen says so.
            "log_window_days": DEFAULT_WINDOW.days,
            "log_window_bounded": not flt.is_narrowed() and flt.from_dt is None,
            "export_qs": filters.query_string(),
            **await fullpage_context(session, current_user),
        },
    )


_EXPORT_LIMIT = 5000
_CSV_COLUMNS = (
    "ts",
    "source",
    "level",
    "name",
    "org_id",
    "org_name",
    "user_id",
    "user_name",
    "entity_id",
    "request_id",
)


def _ndjson(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def _csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter[str](buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@router.get(
    "/export",
    response_class=Response,
    responses={200: {"content": {"application/x-ndjson": {}, "text/csv": {}}}},
)
async def export_timeline(
    current_user: CurrentAdmin,
    session: AdminSession,
    filters: TimelineQueryParams,
    format: str = "ndjson",
) -> Response:
    """Export what the screen's filter selects: NDJSON with the payload, or CSV of the core
    columns."""
    entries = await TimelineReader(session).search(filters.to_filter(), limit=_EXPORT_LIMIT)
    rows = [e.model_dump(mode="json") for e in entries]
    if format == "csv":
        return Response(
            _csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="timeline.csv"'},
        )
    return Response(
        _ndjson(rows),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="timeline.ndjson"'},
    )
