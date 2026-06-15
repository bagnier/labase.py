import uuid

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.learning.domain.models import (
    CardResource,
    DueCard,
    Outcome,
    ResourceRead,
    ReviewCardRead,
)
from app.learning.domain.service import (
    apply_outcome,
    compute_resources,
    needs_resources,
    select_due_cards,
)
from app.learning.infra.repository import CatalogRow, LearningRepository
from app.profile.contract.shell import shell_context
from app.shared import clock
from app.shared.dependencies import CurrentOrg, CurrentOrgModel, CurrentUser, RlsSession
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event

router = APIRouter(prefix="/learning", tags=["learning"])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _level(row: CatalogRow) -> int:
    return row.state.level if row.state else 0


def _due_rows(rows: list[CatalogRow], today) -> list[CatalogRow]:
    by_external = {r.card.external_id: r for r in rows}
    ordered = select_due_cards(
        [
            DueCard(
                external_id=r.card.external_id,
                level=_level(r),
                deck_position=r.deck.position,
                card_position=r.card.position,
                next_review_on=r.state.next_review_on if r.state else None,
            )
            for r in rows
        ],
        today,
    )
    return [by_external[c.external_id] for c in ordered]


async def _render_session(
    request: Request,
    session: AsyncSession,
    current_user: AuthenticatedUser,
    rows: list[CatalogRow],
    org: object,
) -> Response:
    cards = [
        ReviewCardRead(
            external_id=r.card.external_id,
            question=r.card.question,
            level=_level(r),
            deck=r.deck.name,
        )
        for r in rows
    ]
    if _wants_json(request):
        return JSONResponse(
            {"count": len(cards), "cards": [c.model_dump(mode="json") for c in cards]}
        )
    is_htmx = request.headers.get("HX-Request") == "true"
    template = "learning/_session_fragment.html" if is_htmx else "learning/session.html"
    org_handle = request.path_params.get("org_handle", "")
    ctx = {"user": current_user, "cards": cards, "org_handle": org_handle, "org": org}
    if not is_htmx:
        ctx |= await shell_context(session, current_user)
    return templates.TemplateResponse(request, template, ctx)


@router.post("/subscribe", response_class=HTMLResponse)
async def subscribe(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    deck: str = Form(...),
):
    repo = LearningRepository(session, org_id, uuid.UUID(current_user.id))
    found = await repo.get_deck_by_name(deck)
    if found is None:
        raise HTTPException(404, "Deck not found")
    await repo.subscribe(found.id)
    rows = _due_rows(await repo.catalog(), clock.now().date())
    return await _render_session(request, session, current_user, rows, org)


@router.get("/today", response_class=HTMLResponse)
async def today(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    repo = LearningRepository(session, org_id, uuid.UUID(current_user.id))
    rows = _due_rows(await repo.catalog(), clock.now().date())
    return await _render_session(request, session, current_user, rows, org)


@router.get("/cards/{external_id}", response_class=HTMLResponse)
async def card_detail(
    request: Request,
    external_id: str,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
):
    repo = LearningRepository(session, org_id, uuid.UUID(current_user.id))
    card = await repo.get_card_by_external(external_id)
    if card is None:
        raise HTTPException(404, "Card not found")
    state = await repo.get_state(card.id)
    if _wants_json(request):
        return JSONResponse(
            {
                "external_id": card.external_id,
                "question": card.question,
                "answer": card.answer,
                "level": state.level if state else 0,
                "last_reviewed_on": state.last_reviewed_on.isoformat()
                if state and state.last_reviewed_on
                else None,
                "next_review_on": state.next_review_on.isoformat()
                if state and state.next_review_on
                else None,
            }
        )
    org_handle = request.path_params.get("org_handle", "")
    return templates.TemplateResponse(
        request,
        "learning/_answer_fragment.html",
        {"user": current_user, "card": card, "org_handle": org_handle},
    )


@router.post("/cards/{external_id}/mark", response_class=HTMLResponse)
async def mark_card(
    request: Request,
    bg: BackgroundTasks,
    external_id: str,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
    outcome: Outcome = Form(...),
):
    repo = LearningRepository(session, org_id, uuid.UUID(current_user.id))
    card = await repo.get_card_by_external(external_id)
    if card is None:
        raise HTTPException(404, "Card not found")
    today_date = clock.now().date()
    state = await repo.get_state(card.id)
    schedule = apply_outcome(state.level if state else 0, today_date, outcome)
    await repo.apply_schedule(card.id, schedule)
    record_audit_event(
        bg,
        level="info",
        event="learning.card_marked",
        user_id=current_user.id,
        org_id=str(org_id),
        card_id=str(card.id),
        outcome=outcome.value,
    )
    rows = _due_rows(await repo.catalog(), today_date)
    return await _render_session(request, session, current_user, rows, org)


@router.get("/resources", response_class=HTMLResponse)
async def resources(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    org: CurrentOrgModel,
):
    repo = LearningRepository(session, org_id, uuid.UUID(current_user.id))
    rows = await repo.catalog()
    needing = [r for r in rows if needs_resources(_level(r))]
    pairs = compute_resources(
        [
            CardResource(
                deck=r.deck.name,
                deck_position=r.deck.position,
                card_position=r.card.position,
                deck_resource=r.deck.resource,
                card_resource=r.card.resource,
            )
            for r in needing
        ]
    )
    items = [ResourceRead(deck=deck, resource=res) for deck, res in pairs]
    if _wants_json(request):
        return JSONResponse([i.model_dump(mode="json") for i in items])
    org_handle = request.path_params.get("org_handle", "")
    ctx = {"user": current_user, "resources": items, "org_handle": org_handle, "org": org}
    ctx |= await shell_context(session, current_user)
    return templates.TemplateResponse(request, "learning/resources.html", ctx)
