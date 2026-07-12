import csv
import io
import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.admin import resolve_user_emails
from apps.auth.contract.current import CurrentAdmin
from apps.logs.domain.models import LogEntry
from apps.logs.infra.repository import LogFilter, LogReader, request_desc
from apps.organizations.contract.queries import org_handles
from apps.shared.charts import chart_config
from apps.shared.http import wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.settings import SettingRow, get_settings

router = APIRouter(tags=["logs"])

_LOGS_APP = "logs"
_LOG_LEVEL_KEY = "log_level"


def _settings_rows() -> list[SettingRow]:
    """The logs app's own settings, straight from the settings model. The logs screen owns both
    its timeline and its settings surface, so ``GET /console/logs`` carries them together."""
    return get_settings(_LOGS_APP).rows()


def _activity_chart(activity: dict[str, dict[str, int]]) -> dict[str, Any]:
    """The stacked per-day columns over whatever days the filtered window carries.

    Series colors mirror the legend swatches in the template (info/secondary/error),
    which is why the chart's own legend stays off."""
    days = sorted(activity)
    series = [
        {"name": source, "data": [activity[d].get(source, 0) for d in days]}
        for source in ("request", "event", "issue")
    ]
    return chart_config(
        "bar",
        series,
        colors=["info", "secondary", "error"],
        chart={"height": 130, "stacked": True},
        xaxis={"categories": [d[5:] for d in days]},
        yaxis={"min": 0, "forceNiceScale": True},
        legend={"show": False},
    )


def _bound(value: str | None) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value (or a bare date), treated as UTC."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _filter(
    source: str | None,
    app: str | None,
    level: str | None,
    org_id: str | None,
    user_id: str | None,
    entity_id: str | None,
    request_id: str | None,
    q: str | None,
    from_dt: str | None,
    to_dt: str | None,
    sort: str,
    dir: str,
) -> LogFilter:
    return LogFilter(
        source=source or None,
        app=app or None,
        level=level or None,
        org_id=org_id or None,
        user_id=user_id or None,
        entity_id=entity_id or None,
        request_id=request_id or None,
        text=q or None,
        from_dt=_bound(from_dt),
        to_dt=_bound(to_dt),
        sort=sort or "ts",
        descending=(dir != "asc"),
    )


def _short(value: str) -> str:
    """The compact display for an opaque id — mirrors the timeline's 8-char truncation."""
    return value[:8]


def _as_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _ids(
    facet: list[dict[str, Any]], entries: list[LogEntry], attr: str, selected: str | None
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
    no org row (background/app logs, test fixtures) fall back to the short id."""
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


def _request_routes(facet: list[dict[str, Any]], entries: list[LogEntry]) -> dict[str, str]:
    """A ``request_id -> route`` map: the facet already carries a route per request over its window;
    supplement it from the visible rows so a request narrowed outside that window still resolves."""
    routes = {o["value"]: o["label"] for o in facet}
    for e in entries:
        if e.request_id and (desc := request_desc(e)):
            routes[e.request_id] = desc
    return routes


@router.get("", response_model=None)
async def logs_screen(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    source: str | None = None,
    app: str | None = None,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    q: str | None = None,
    from_dt: str | None = None,
    to_dt: str | None = None,
    sort: str = "ts",
    dir: str = "desc",
) -> Response:
    flt = _filter(
        source, app, level, org_id, user_id, entity_id, request_id, q, from_dt, to_dt, sort, dir
    )
    reader = LogReader(session)
    entries = await reader.search(flt)
    activity = await reader.activity(flt)
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
    if wants_json(request):
        return JSONResponse(
            {
                "app": _LOGS_APP,
                "entries": [e.model_dump(mode="json") for e in entries],
                "activity": activity,
                "facets": facets,
                "settings": settings,
            }
        )
    filters = {
        "source": source or "",
        "app": app or "",
        "level": level or "",
        "org_id": org_id or "",
        "user_id": user_id or "",
        "entity_id": entity_id or "",
        "request_id": request_id or "",
        "q": q or "",
        "from_dt": from_dt or "",
        "to_dt": to_dt or "",
    }
    return templates.TemplateResponse(
        request,
        "logs/index.html",
        {
            "user": current_user,
            "entries": entries,
            "activity": activity,
            "activity_chart": _activity_chart(activity),
            "facets": facets,
            "org_label": org_label,
            "user_label": user_label,
            "request_label": request_label,
            "labels": row_labels,
            # Only the firehose level is tuned from the screen; the enabled switch stays on the
            # console's app page like every other app.
            "settings": [r for r in settings if r["key"] == _LOG_LEVEL_KEY],
            "filters": filters,
            "sort": flt.sort,
            "dir": "desc" if flt.descending else "asc",
            "export_qs": urlencode({k: v for k, v in filters.items() if v}),
            **await fullpage_context(session, current_user),
        },
    )


_EXPORT_LIMIT = 5000
_CSV_COLUMNS = ("ts", "source", "level", "event", "org_id", "user_id", "entity_id", "request_id")


def _ndjson(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r) + "\n" for r in rows)


def _csv(rows: list[dict[str, Any]]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=_CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


@router.get("/export", response_model=None)
async def export_logs(
    current_user: CurrentAdmin,
    session: AdminSession,
    format: str = "ndjson",
    source: str | None = None,
    app: str | None = None,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    entity_id: str | None = None,
    request_id: str | None = None,
    q: str | None = None,
    from_dt: str | None = None,
    to_dt: str | None = None,
    sort: str = "ts",
    dir: str = "desc",
) -> Response:
    """Structured export of the *current filter's* window — the same LogFilter the timeline uses,
    so what you see is what you download. NDJSON keeps the nested payload; CSV flattens the core
    columns for a spreadsheet."""
    flt = _filter(
        source, app, level, org_id, user_id, entity_id, request_id, q, from_dt, to_dt, sort, dir
    )
    entries = await LogReader(session).search(flt, limit=_EXPORT_LIMIT)
    rows = [e.model_dump(mode="json") for e in entries]
    if format == "csv":
        return Response(
            _csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": 'attachment; filename="logs.csv"'},
        )
    return Response(
        _ndjson(rows),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": 'attachment; filename="logs.ndjson"'},
    )
