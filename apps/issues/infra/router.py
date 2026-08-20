import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from apps.auth.contract.current import CurrentAdmin
from apps.issues.contract.events import IssueStatusChanged
from apps.issues.domain.models import Issue, IssueRead, IssueStatus, OccurrenceRead
from apps.issues.infra.repository import IssueRepository
from apps.shared import clock
from apps.shared.charts import last_days, sparkline
from apps.shared.events.bus import events
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.settings.env import get_technical_settings

router = APIRouter(tags=["issues"])

_TRIAGE_STATUSES = {IssueStatus.resolved, IssueStatus.ignored, IssueStatus.unresolved}
_SPARK_DAYS = 14


def _known_status(raw: str, allowed: set[IssueStatus]) -> IssueStatus:
    """Narrow a raw query/form value to the enum, or refuse it here.

    Both inputs end up compared against the Postgres ``issue_status`` column, where an unknown
    value raises down in the driver — a 500, and an issue about the crafted request itself.
    """
    if raw not in {s.value for s in allowed}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown status")
    return IssueStatus(raw)


def _status_filter(raw: str) -> IssueStatus | None:
    """The console dropdown's value; empty is its "all" option, and means no filter."""
    return _known_status(raw, set(IssueStatus)) if raw else None


def _triage_status(raw: str) -> IssueStatus:
    """The status a human may set. ``new`` and ``regressed`` are the tracker's own verdicts."""
    return _known_status(raw, _TRIAGE_STATUSES)


async def _issue_or_404(repo: IssueRepository, issue_id: uuid.UUID) -> Issue:
    issue = await repo.get(issue_id)
    if issue is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return issue


@router.get("", response_model=None)
async def list_issues(
    request: Request,
    current_user: CurrentAdmin,
    session: AdminSession,
    status_filter: str = "",
) -> Response:
    selected = _status_filter(status_filter)
    issues = [
        IssueRead.model_validate(i)
        for i in await IssueRepository(session).list_issues(status=selected)
    ]
    if wants_json(request):
        return JSONResponse([i.model_dump(mode="json") for i in issues])
    return templates.TemplateResponse(
        request,
        "issues/index.html",
        {
            "user": current_user,
            "issues": issues,
            "status_filter": status_filter,
            "statuses": [s.value for s in IssueStatus],
            **await fullpage_context(session, current_user),
        },
    )


@router.get("/{issue_id}", response_model=None)
async def issue_detail(
    request: Request,
    issue_id: uuid.UUID,
    current_user: CurrentAdmin,
    session: AdminSession,
    before_id: uuid.UUID | None = None,
) -> Response:
    repo = IssueRepository(session)
    issue = await _issue_or_404(repo, issue_id)
    occurrences, next_before_id = await repo.occurrences(issue_id, before_id=before_id)
    issue_read = IssueRead.model_validate(issue)
    occurrence_reads = [OccurrenceRead.model_validate(o) for o in occurrences]
    if wants_json(request):
        return JSONResponse(
            {
                "issue": issue_read.model_dump(mode="json"),
                "occurrences": [o.model_dump(mode="json") for o in occurrence_reads],
                "next_before_id": str(next_before_id) if next_before_id else None,
            }
        )
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "issues/_occurrences.html" if is_htmx else "issues/detail.html"
    ctx: dict[str, Any] = {
        "user": current_user,
        "issue": issue_read,
        "occurrences": occurrence_reads,
        "next_before_id": next_before_id,
    }
    if not is_htmx:
        counts = await repo.daily_counts(issue_id, days=_SPARK_DAYS)
        window = last_days(_SPARK_DAYS, end=clock.now().date())
        ctx["spark"] = sparkline([counts.get(d.isoformat(), 0) for d in window], color="error")
        ctx["spark_days"] = _SPARK_DAYS
        ctx |= await fullpage_context(session, current_user)
    return templates.TemplateResponse(request, template, ctx)


@router.post("/{issue_id}/status", response_model=None)
async def set_issue_status(
    request: Request,
    issue_id: uuid.UUID,
    current_user: CurrentAdmin,
    session: AdminSession,
) -> Response:
    body = await parse_body(request)
    new_status = _triage_status(str(body.get("status", "")))
    repo = IssueRepository(session)
    issue = await _issue_or_404(repo, issue_id)
    await repo.set_status(issue, new_status, get_technical_settings().app_version)
    # Emit on the request session: the status-change fact commits iff the status does (auto-commit
    # at request teardown, like every other business route — no explicit commit here).
    await events.emit(
        IssueStatusChanged(
            user_id=current_user.id,
            entity_id=issue_id,
            entity_name=issue.title,
            status=new_status.value,
        ),
        session,
    )
    issue_read = IssueRead.model_validate(issue)
    if wants_json(request):
        return JSONResponse(issue_read.model_dump(mode="json"))
    return templates.TemplateResponse(request, "issues/_triage.html", {"issue": issue_read})
