import uuid

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from app.auth.infra.user_repository import find_user_id_by_email, resolve_user_emails
from app.organizations.domain.exceptions import PendingInvitationExists
from app.organizations.domain.models import InvitationRead, MemberRead, OrgRole
from app.organizations.domain.service import ensure_no_pending_invitation
from app.organizations.infra.repository import OrganizationRepository
from app.profile.contract.shell import page_context
from app.shared.dependencies import (
    CurrentMembership,
    CurrentOrg,
    CurrentOwnerMembership,
    CurrentUser,
    RlsSession,
)
from app.shared.http.templates import templates
from app.shared.names import is_reserved, is_valid_handle

router = APIRouter(tags=["organizations-html"])


# ── Dashboard ─────────────────────────────────────────────────────────────────


@router.get("/dashboard", response_class=HTMLResponse)
async def org_dashboard(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> HTMLResponse:
    repo = OrganizationRepository(session)
    org = await repo.get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await page_context(session, current_user, org=org, org_handle=org_handle)
    return templates.TemplateResponse(request, "organizations/dashboard.html", ctx)


# ── Settings ─────────────────────────────────────────────────────────────────


@router.get("/settings", response_class=HTMLResponse)
async def org_settings(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
):
    repo = OrganizationRepository(session)
    org = await repo.get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await page_context(
        session, current_user, org=org, org_handle=org_handle, role=membership.role.value
    )
    return templates.TemplateResponse(request, "organizations/settings.html", ctx)


@router.patch("", response_class=HTMLResponse)
async def rename_org_html(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
    name: str = Form(..., min_length=1, max_length=255),
):
    repo = OrganizationRepository(session)
    org = await repo.get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await repo.rename(org, name)
    return RedirectResponse(url=f"/{org.handle}/settings", status_code=303)


@router.patch("/handle", response_class=HTMLResponse)
async def update_org_handle_html(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
    handle: str = Form(...),
):
    repo = OrganizationRepository(session)
    org = await repo.get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    handle = handle.strip().lower()
    org_handle = request.path_params.get("org_handle", org.handle)
    if not is_valid_handle(handle):
        ctx = await page_context(
            session, current_user, org=org, org_handle=org_handle, role=membership.role.value
        )
        ctx["handle_error"] = "Handle must be lowercase alphanumeric with hyphens, max 39 chars."
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=422
        )
    if is_reserved(handle):
        ctx = await page_context(
            session, current_user, org=org, org_handle=org_handle, role=membership.role.value
        )
        ctx["handle_error"] = f"'{handle}' is a reserved name."
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=422
        )
    if not await repo.is_handle_available(handle, org_id):
        ctx = await page_context(
            session, current_user, org=org, org_handle=org_handle, role=membership.role.value
        )
        ctx["handle_error"] = f"'{handle}' is already taken."
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=409
        )
    await repo.update_handle(org, handle)
    return RedirectResponse(url=f"/{handle}/settings", status_code=303)


# ── Members ───────────────────────────────────────────────────────────────────


@router.get("/members", response_class=HTMLResponse)
async def org_members(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
):
    repo = OrganizationRepository(session)
    org = await repo.get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    raw_members = await repo.list_members(org_id)
    emails = await resolve_user_emails([m.auth_user_id for m in raw_members])
    members = [
        MemberRead(
            auth_user_id=m.auth_user_id,
            email=emails.get(m.auth_user_id, ""),
            role=m.role,
            created_at=m.created_at,
        )
        for m in raw_members
    ]
    invitations: list[InvitationRead] = []
    if membership.role == OrgRole.owner:
        raw_invs = await repo.list_invitations(org_id)
        invitations = [InvitationRead.model_validate(inv) for inv in raw_invs]

    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await page_context(
        session,
        current_user,
        current_user=current_user,
        org=org,
        org_handle=org_handle,
        caller_role=membership.role.value,
        members=members,
        invitations=invitations,
    )
    return templates.TemplateResponse(request, "organizations/members.html", ctx)


# ── Invite (HTMX) ─────────────────────────────────────────────────────────────


@router.post("/invitations", response_class=HTMLResponse)
async def create_invitation_html(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
    email: str = Form(...),
):
    error: str | None = None
    link: str = ""

    existing_user_id = await find_user_id_by_email(email)
    if existing_user_id is not None:
        existing_membership = await OrganizationRepository(session).get_membership(
            org_id, existing_user_id
        )
        if existing_membership is not None:
            error = "already a member"

    if error is None:
        repo = OrganizationRepository(session)
        try:
            await ensure_no_pending_invitation(repo, org_id, email)
        except PendingInvitationExists as exc:
            error = str(exc)
        else:
            invitation = await repo.create_invitation(
                org_id=org_id,
                email=email,
                role=OrgRole.member,
                invited_by=uuid.UUID(current_user.id),
            )
            base_url = str(request.base_url).rstrip("/")
            link = f"{base_url}/invitations/{invitation.token}"

    return templates.TemplateResponse(
        request,
        "organizations/_invite_result.html",
        {"email": email, "link": link, "error": error},
    )
