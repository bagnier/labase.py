import uuid

from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import text

from app.organizations.domain.exceptions import PendingInvitationExists
from app.organizations.domain.models import InvitationRead, MemberRead, OrgRole
from app.organizations.domain.service import ensure_no_pending_invitation
from app.organizations.infra.repository import OrganizationRepository, resolve_emails
from app.shared.dependencies import (
    AdminSession,
    CurrentMembership,
    CurrentOrg,
    CurrentUser,
    RlsSession,
)
from app.shared.http.templates import templates

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
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    org_slug = request.path_params.get("org_slug", org.slug)
    return templates.TemplateResponse(
        request,
        "organizations/dashboard.html",
        {"user": current_user, "org": org, "org_slug": org_slug},
    )


# ── Settings ─────────────────────────────────────────────────────────────────


@router.get("/settings", response_class=HTMLResponse)
async def org_settings(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
):
    repo = OrganizationRepository(session)
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    org_slug = request.path_params.get("org_slug", org.slug)
    return templates.TemplateResponse(
        request,
        "organizations/settings.html",
        {
            "user": current_user,
            "org": org,
            "org_slug": org_slug,
            "role": membership.role.value,
        },
    )


@router.patch("", response_class=HTMLResponse)
async def rename_org_html(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
    name: str = Form(...),
):
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    repo = OrganizationRepository(session)
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    await repo.rename(org, name)
    # Reload org to get new slug
    org = await repo.get_by_id(org_id)
    assert org is not None
    return RedirectResponse(url=f"/{org.slug}/settings", status_code=303)


# ── Members ───────────────────────────────────────────────────────────────────


@router.get("/members", response_class=HTMLResponse)
async def org_members(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    admin_session: AdminSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
):
    repo = OrganizationRepository(session)
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    raw_members = await repo.list_members(org_id)
    emails = await resolve_emails(admin_session, [m.auth_user_id for m in raw_members])
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

    org_slug = request.path_params.get("org_slug", org.slug)
    return templates.TemplateResponse(
        request,
        "organizations/members.html",
        {
            "user": current_user,
            "current_user": current_user,
            "org": org,
            "org_slug": org_slug,
            "caller_role": membership.role.value,
            "members": members,
            "invitations": invitations,
        },
    )


# ── Invite (HTMX) ─────────────────────────────────────────────────────────────


@router.post("/invitations", response_class=HTMLResponse)
async def create_invitation_html(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    admin_session: AdminSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
    email: str = Form(...),
):
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")

    error: str | None = None
    link: str = ""

    result = await admin_session.execute(
        text("SELECT id FROM auth.users WHERE lower(email) = lower(:email)"),
        {"email": email},
    )
    existing_user = result.first()
    if existing_user is not None:
        existing_membership = await OrganizationRepository(session).get_membership(
            org_id, existing_user.id
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
