from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.issues.domain.models import ErrorEventRead, ErrorGroupRead, IssueStatus
from apps.issues.infra.repository import ErrorGroupRepository
from apps.shared.config import get_technical_settings
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["issues"])

_TRIAGE_STATUSES = {IssueStatus.resolved, IssueStatus.ignored, IssueStatus.unresolved}


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
    group = await repo.get(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
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
    ctx = {
        "user": current_user,
        "group": group_read,
        "events": event_reads,
        "next_before_id": next_before_id,
    }
    if not is_htmx:
        ctx |= await fullpage_context(session, current_user)
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{group_id}/status", response_model=None)
async def set_issue_status(
    request: Request,
    bg: BackgroundTasks,
    group_id: int,
    current_user: CurrentAdmin,
    session: AdminSession,
) -> Response:
    body = await parse_body(request)
    try:
        new_status = IssueStatus(str(body.get("status", "")))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown status"
        ) from None
    if new_status not in _TRIAGE_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown status")
    repo = ErrorGroupRepository(session)
    group = await repo.get(group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await repo.set_status(group, new_status, get_technical_settings().app_version)
    await session.commit()
    audit(
        bg,
        "issues.status_changed",
        user_id=current_user.id,
        group_id=str(group_id),
        status=new_status.value,
    )
    group_read = ErrorGroupRead.model_validate(group)
    if wants_json(request):
        return JSONResponse(group_read.model_dump(mode="json"))
    return templates.TemplateResponse(request, "issues/_triage.html", {"group": group_read})
