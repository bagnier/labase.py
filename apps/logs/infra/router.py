from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.logs.infra.repository import LogFilter, LogReader
from apps.shared.http import wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["logs"])


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
                "entries": [e.model_dump(mode="json") for e in entries],
                "activity": activity,
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
