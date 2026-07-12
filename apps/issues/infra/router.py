from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.issues.contract.events import IssueStatusChanged
from apps.issues.domain.models import ErrorEventRead, ErrorGroup, ErrorGroupRead, IssueStatus
from apps.issues.infra.repository import ErrorGroupRepository
from apps.shared import clock
from apps.shared.bus import bus
from apps.shared.charts import last_days, sparkline
from apps.shared.config import get_technical_settings
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["issues"])

_TRIAGE_STATUSES = {IssueStatus.resolved, IssueStatus.ignored, IssueStatus.unresolved}
_SPARK_DAYS = 14


async def _group_or_404(repo: ErrorGroupRepository, group_id: int) -> ErrorGroup:
    group = await repo.get(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return group


@router.get("", response_model=None)
async def list_issues(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    status_filter: str = "",
) -> Response:
    groups = [
        ErrorGroupRead.model_validate(g)
        for g in await ErrorGroupRepository(session).list_groups(status=status_filter)
    ]
    if wants_json(request):
        return JSONResponse([g.model_dump(mode="json") for g in groups])
    return templates.TemplateResponse(
        request,
        "issues/index.html",
        {
            "user": current_user,
            "groups": groups,
            "status_filter": status_filter,
            "statuses": [s.value for s in IssueStatus],
            **await fullpage_context(session, current_user),
        },
    )


@router.get("/{group_id}", response_model=None)
async def issue_detail(
    request: Request,
    group_id: int,
    current_user: CurrentAdmin,
    session: AdminSession,
    before_id: int | None = None,
) -> Response:
    repo = ErrorGroupRepository(session)
    group = await _group_or_404(repo, group_id)
    events, next_before_id = await repo.events(group_id, before_id=before_id)
    group_read = ErrorGroupRead.model_validate(group)
    event_reads = [ErrorEventRead.model_validate(e) for e in events]
    if wants_json(request):
        return JSONResponse(
            {
                "group": group_read.model_dump(mode="json"),
                "events": [e.model_dump(mode="json") for e in event_reads],
                "next_before_id": next_before_id,
            }
        )
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "issues/_events.html" if is_htmx else "issues/detail.html"
    ctx: dict[str, Any] = {
        "user": current_user,
        "group": group_read,
        "events": event_reads,
        "next_before_id": next_before_id,
    }
    if not is_htmx:
        counts = await repo.daily_counts(group_id, days=_SPARK_DAYS)
        window = last_days(_SPARK_DAYS, end=clock.now().date())
        ctx["spark"] = sparkline([counts.get(d.isoformat(), 0) for d in window], color="error")
        ctx["spark_days"] = _SPARK_DAYS
        ctx |= await fullpage_context(session, current_user)
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{group_id}/status", response_model=None)
async def set_issue_status(
    request: Request,
    group_id: int,
    current_user: CurrentAdmin,
    session: AdminSession,
) -> Response:
    body = await parse_body(request)
    raw = str(body.get("status", ""))
    if raw not in {s.value for s in _TRIAGE_STATUSES}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown status")
    new_status = IssueStatus(raw)
    repo = ErrorGroupRepository(session)
    group = await _group_or_404(repo, group_id)
    await repo.set_status(group, new_status, get_technical_settings().app_version)
    await session.commit()
    await bus.emit(
        IssueStatusChanged(
            actor_id=current_user.id, entity_id=str(group_id), status=new_status.value
        )
    )
    group_read = ErrorGroupRead.model_validate(group)
    if wants_json(request):
        return JSONResponse(group_read.model_dump(mode="json"))
    return templates.TemplateResponse(request, "issues/_triage.html", {"group": group_read})
