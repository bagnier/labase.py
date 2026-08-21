import csv
import io
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, ClassVar
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.admin import resolve_user_emails
from apps.auth.contract.current import CurrentAdmin
from apps.organizations.contract.queries import org_handles
from apps.shared import clock
from apps.shared.charts import chart_config
from apps.shared.http import JSON_AND_HTML, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.logs.repository import DEFAULT_WINDOW
from apps.shared.persistence.database import AdminSession
from apps.shared.settings.live import SettingRow, get_settings
from apps.timeline.domain.models import TimelineEntry
from apps.timeline.infra.repository import TimelineFilter, TimelineReader, request_desc

router = APIRouter(tags=["timeline"])

_TIMELINE_APP = "timeline"
_LOG_LEVEL_KEY = "log_level"
# How many rows one read of the screen answers with, and therefore what a full page looks like:
# a page that comes back full is the signal there may be more below it.
_PAGE_SIZE = 100


def _settings_rows() -> list[SettingRow]:
    """The app's own settings, straight from the settings model. The screen owns both its
    timeline and its settings surface, so ``GET /console/timeline`` carries them together."""
    return get_settings(_TIMELINE_APP).rows()


_GRAINS = ("hour", "day", "week", "month")
# ``(source value, human series label)`` — the label rides the ApexCharts tooltip, and the colors
# mirror the template's legend swatches (info/secondary/error), which is why the chart's own legend
# stays off.
_SOURCE_SERIES = (("logs", "Logs"), ("business", "Business"), ("issue", "Issue"))

# How many buckets the x-axis shows per grain — a *fixed* count ending at the current period, so the
# axis width is stable and bounded however the data clusters. Aligned with the data windows in
# ``repository._GRAIN_WINDOW``.
_GRAIN_SPAN = {"hour": 24, "day": 14, "week": 12, "month": 12}


def _bucket_label(key: str, grain: str) -> str:
    """The compact x-axis label for a bucket key at the given grain."""
    if grain == "hour":
        return key[11:16]  # HH:00
    if grain == "week":
        return key.split("-", 1)[1]  # W##
    if grain == "month":
        return key  # YYYY-MM
    return key[5:]  # MM-DD (day)


def _axis_keys(grain: str, now: datetime) -> list[str]:
    """The fixed run of consecutive bucket keys ending at the current period — the chart's x-axis.
    Fixed-length (see ``_GRAIN_SPAN``) so the axis stays a stable, bounded width; buckets with no
    data render as zero columns rather than collapsing the timeline."""
    n = _GRAIN_SPAN[grain]
    ago = range(n - 1, -1, -1)  # oldest bucket first, current period last
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
    activity: dict[str, dict[str, int]], grain: str, now: datetime
) -> dict[str, Any]:
    """The stacked columns over the grain's fixed window ending now. Per-bucket tick marks are
    hidden and labels thinned to ~6, so even a 24-column hour view reads cleanly; the y-axis gets
    height and four gridlines for gradation."""
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
            "tickAmount": 6,  # ApexCharts thins the labels evenly to at most this many
            "axisTicks": {"show": False},  # drop the per-bucket tick marks that crowd the axis
            "labels": {"rotate": 0, "hideOverlappingLabels": True},
        },
        yaxis={"min": 0, "forceNiceScale": True, "tickAmount": 4},
        grid={"padding": {"left": 8, "right": 8}},
        legend={"show": False},
    )


def _bound(value: str) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value (or a bare date), treated as UTC. An empty
    field is no bound at all — the one thing a form can say for "I left this alone"."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


@dataclass(frozen=True)
class TimelineQuery:
    """The screen's filter *as the query string carries it* — every field a plain string,
    where empty means "not filtered".

    This is deliberately a different shape from the reader's :class:`TimelineFilter`, which says
    absence with ``None``. A form field can only be present-and-empty, so modelling these as
    optional strings gave three states (absent / ``""`` / value) for two meanings, and every
    caller had to collapse them. Here the HTML shape stays total, :meth:`to_filter` is the one
    place it becomes the domain shape, and the screen, the export and the template read one object.
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
    # The paging cursor: the ISO timestamp of the oldest row already shown.
    before: str = ""

    # sort/dir/before are the view's own state, not filters: they ride their own params on a link.
    # ``before`` especially — carried into an export or a re-sort it would silently cut the result
    # off at whatever page the reader happened to have scrolled to.
    _ORDERING: ClassVar[tuple[str, ...]] = ("sort", "dir", "before")

    def to_filter(self) -> TimelineFilter:
        """The reader's contract, where "no filter" is ``None`` — the one boundary conversion."""
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
        """The filters actually set — what a sort/grain/export link must carry along."""
        return {
            f.name: value
            for f in fields(self)
            if f.name not in self._ORDERING and (value := getattr(self, f.name))
        }

    def query_string(self) -> str:
        return urlencode(self.active())


TimelineQueryParams = Annotated[TimelineQuery, Depends()]


def _short(value: str) -> str:
    """The compact display for an opaque id — mirrors the timeline's 8-char truncation."""
    return value[:8]


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _ids(
    facet: list[dict[str, Any]], entries: list[TimelineEntry], attr: str, selected: str | None
) -> set[str]:
    """Every id that needs a label for this dimension: the facet options, the visible rows' ids,
    and the current selection — deduplicated so the resolver is called once."""
    values = {o["value"] for o in facet}
    values |= {v for e in entries if (v := getattr(e, attr))}
    if selected:
        values.add(selected)
    return values


async def _org_labeler(session: AdminSession, values: set[str]) -> Callable[[str], str]:
    """A ``value -> handle`` labeller over the given org ids, resolved in one bulk lookup. Ids with
    no org (background/app lines, test fixtures) fall back to the short id."""
    uuids = {_as_uuid(v) for v in values}
    handles = await org_handles(session, {i for i in uuids if i is not None})

    def label(value: str) -> str:
        oid = _as_uuid(value)
        return handles.get(oid, _short(value)) if oid else _short(value)

    return label


async def _user_labeler(values: set[str]) -> Callable[[str], str]:
    """A ``value -> email`` labeller over the given user ids, resolved in bulk from the auth admin
    API. Ids the directory can't resolve (deleted users, fixtures) fall back to the short id."""
    uuids = {_as_uuid(v) for v in values}
    emails = await resolve_user_emails([i for i in uuids if i is not None])

    def label(value: str) -> str:
        uid = _as_uuid(value)
        return (emails.get(uid) or _short(value)) if uid else _short(value)

    return label


def _request_routes(facet: list[dict[str, Any]], entries: list[TimelineEntry]) -> dict[str, str]:
    """A ``request_id -> route`` map: the facet already carries a route per request over its window;
    supplement it from the visible rows so a request narrowed outside that window still resolves."""
    routes = {o["value"]: o["label"] for o in facet}
    for e in entries:
        if e.request_id and (desc := request_desc(e)):
            routes[e.request_id] = desc
    return routes


def _next_cursor(entries: list[TimelineEntry], flt: TimelineFilter) -> str | None:
    """The cursor for the page below this one, or ``None`` when there is nothing left to offer.

    Only on the default newest-first order. Any other column sorts the *loaded page* and says so
    (``data-sort-scope``) — offering to continue a sample would promise an ordering the reader
    does not have, and each further page would be a sample of a sample.

    A full page is the signal: the reader cannot tell "exactly a hundred left" from "a hundred and
    more", and asking it to would cost a second query on every view to spare one empty click.
    """
    if len(entries) < _PAGE_SIZE or flt.sort != "ts" or not flt.descending:
        return None
    return entries[-1].ts.isoformat()


@router.get("", responses=JSON_AND_HTML)
async def timeline_screen(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    filters: TimelineQueryParams,
    bucket: str = "day",
) -> Response:
    flt = filters.to_filter()
    org_id, user_id, request_id = filters.org_id, filters.user_id, filters.request_id
    grain = bucket if bucket in _GRAINS else "day"
    reader = TimelineReader(session)
    entries = await reader.search(flt, limit=_PAGE_SIZE)
    activity = await reader.activity(flt, grain=grain)
    facets = await reader.facets(flt)

    # Resolve ids to intelligible names once, over the union of the facet options (the pill
    # dropdowns) and the ids on the visible rows (the table) — one bulk lookup feeds both.
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
    # A "load older" click asks for rows, not for a screen: the chart, the facets and the label
    # lookups above are the page's, and re-rendering them would swap them out from under the
    # reader. The button replaces itself with the next batch and its own successor.
    if request.headers.get("HX-Request") == "true":
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
            # Only the log level is tuned from the screen; the enabled switch stays on the
            # console's app page like every other app.
            "settings": [r for r in settings if r["key"] == _LOG_LEVEL_KEY],
            "filters": filters,
            "sort": flt.sort,
            "dir": "desc" if flt.descending else "asc",
            # The three sources do not share a memory, and only one of them says so. Stated on
            # screen rather than left to be discovered by a correlation that came back short —
            # the same move as ``data-sort-scope`` one section down.
            "log_window_days": DEFAULT_WINDOW.days,
            "log_window_bounded": not flt.is_narrowed() and flt.from_dt is None,
            "export_qs": filters.query_string(),
            **await fullpage_context(session, current_user),
        },
    )


_EXPORT_LIMIT = 5000
_CSV_COLUMNS = ("ts", "source", "level", "name", "org_id", "user_id", "entity_id", "request_id")


def _ndjson(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def _csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter[str](buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@router.get("/export", response_model=None)
async def export_timeline(
    current_user: CurrentAdmin,
    session: AdminSession,
    filters: TimelineQueryParams,
    format: str = "ndjson",
) -> Response:
    """Structured export of the *current filter's* window — the same TimelineFilter the screen
    uses, so what you see is what you download. NDJSON keeps the nested payload; CSV flattens
    the core columns for a spreadsheet."""
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
