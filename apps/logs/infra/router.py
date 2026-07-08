import csv
import io
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.logs.infra.repository import LogFilter, LogReader
from apps.shared.host import host
from apps.shared.http import wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.settings import get_settings

router = APIRouter(tags=["logs"])

_LOGS_APP = "logs"


def _settings_block() -> list[dict[str, Any]]:
    """The logs app's own settings (the firehose level), rendered for the consolidated screen.

    The logs screen owns both its timeline and its settings surface, so ``GET /console/logs``
    carries them together — no separate settings page to reach the level control."""
    group = host.declared_settings(_LOGS_APP)
    values = get_settings(_LOGS_APP).values
    if group is None:
        return []
    return [
        {"key": d.key, "type": d.type, "label": d.label, "value": values.get(d.key, d.default)}
        for d in group.defs
    ]


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
    if wants_json(request):
        return JSONResponse(
            {
                "app": _LOGS_APP,
                "entries": [e.model_dump(mode="json") for e in entries],
                "activity": activity,
                "settings": _settings_block(),
            }
        )
    return templates.TemplateResponse(
        request,
        "logs/index.html",
        {
            "user": current_user,
            "entries": entries,
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
