import csv
import io
import json
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.logs.infra.repository import LogFilter, LogReader
from apps.organizations.contract.queries import org_handles
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


def _bound(value: str | None) -> datetime | None:
    """Parse a ``<input type="datetime-local">`` value (or a bare date), treated as UTC."""
    if not value:
        return None
    return datetime.fromisoformat(value).replace(tzinfo=UTC)


def _filter(
    source: str | None,
    level: str | None,
    org_id: str | None,
    user_id: str | None,
    request_id: str | None,
    q: str | None,
    from_dt: str | None,
    to_dt: str | None,
    sort: str,
    dir: str,
) -> LogFilter:
    return LogFilter(
        source=source or None,
        level=level or None,
        org_id=org_id or None,
        user_id=user_id or None,
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


async def _label_orgs(session: AdminSession, org_facet: list[dict[str, Any]], selected: str) -> str:
    """Resolve every org id in the org facet (and the currently selected one) to its handle,
    annotating each option in place with a ``label`` and returning the selected value's label.
    Handles are looked up in bulk; ids with no org row (background/app logs, test fixtures) fall
    back to the short id."""
    ids = {_as_uuid(o["value"]) for o in org_facet}
    ids.add(_as_uuid(selected))
    handles = await org_handles(session, {i for i in ids if i is not None})

    def label(value: str) -> str:
        oid = _as_uuid(value)
        return handles.get(oid, _short(value)) if oid else _short(value)

    for option in org_facet:
        option["label"] = label(option["value"])
    return label(selected) if selected else ""


@router.get("", response_model=None)
async def logs_screen(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    source: str | None = None,
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
    request_id: str | None = None,
    q: str | None = None,
    from_dt: str | None = None,
    to_dt: str | None = None,
    sort: str = "ts",
    dir: str = "desc",
) -> Response:
    flt = _filter(source, level, org_id, user_id, request_id, q, from_dt, to_dt, sort, dir)
    reader = LogReader(session)
    entries = await reader.search(flt)
    activity = await reader.activity(flt)
    facets = await reader.facets(flt)
    org_label = await _label_orgs(session, facets["org"], org_id or "")
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
        "level": level or "",
        "org_id": org_id or "",
        "user_id": user_id or "",
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
            "facets": facets,
            "org_label": org_label,
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
_CSV_COLUMNS = ("ts", "source", "level", "event", "org_id", "user_id", "request_id")


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
    level: str | None = None,
    org_id: str | None = None,
    user_id: str | None = None,
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
    flt = _filter(source, level, org_id, user_id, request_id, q, from_dt, to_dt, sort, dir)
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
