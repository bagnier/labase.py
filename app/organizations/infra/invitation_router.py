import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import DBAPIError

from app.organizations.domain.models import InvitationRead, InvitationStatus
from app.organizations.infra.repository import OrganizationRepository
from app.shared.dependencies import AdminSession, CurrentUser, OptionalCurrentUser, RlsSession
from app.shared.http import wants_json
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event
from app.shared.persistence.supabase import auth_user_exists

log = structlog.get_logger("labase.organizations.invitations")

router = APIRouter(prefix="/invitations", tags=["invitations"])


async def _get_admin_org_repo(admin_session: AdminSession) -> OrganizationRepository:
    return OrganizationRepository(admin_session)


async def _get_rls_org_repo(rls_session: RlsSession) -> OrganizationRepository:
    return OrganizationRepository(rls_session)


AdminOrgRepo = Annotated[OrganizationRepository, Depends(_get_admin_org_repo)]
RlsOrgRepo = Annotated[OrganizationRepository, Depends(_get_rls_org_repo)]


@router.get("/{token}", response_model=None)
async def get_invitation(
    request: Request,
    token: uuid.UUID,
    admin_session: AdminSession,
    repo: AdminOrgRepo,
    current_user: OptionalCurrentUser,
):
    invitation = await repo.get_invitation_by_token(token)

    if wants_json(request):
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found or already used",
            )
        if invitation["status"] == "revoked":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found or already used",
            )
        return InvitationRead(
            id=invitation["id"],
            org_id=invitation["org_id"],
            email=invitation["email"],
            role=invitation["role"],
            token=invitation["token"],
            status=InvitationStatus(invitation["status"]),
            created_at=invitation["created_at"],
        )

    # HTML response
    if invitation is None:
        return templates.TemplateResponse(
            request,
            "invitations/accept.html",
            {"state": "invalid", "token": str(token), "org_name": "", "email": ""},
            status_code=404,
        )
    org = await repo.get(invitation["org_id"])
    org_name = org.name if org else ""
    if invitation["status"] == "accepted":
        state = "already_accepted"
    elif invitation["status"] == "revoked":
        state = "invalid"
    else:
        email = invitation.get("email", "")
        if current_user is not None:
            state = "valid"
        else:
            account_exists = await auth_user_exists(admin_session, email)
            state = "valid_login" if account_exists else "valid_register"
    return templates.TemplateResponse(
        request,
        "invitations/accept.html",
        {
            "state": state,
            "token": str(token),
            "org_name": org_name,
            "email": invitation.get("email", ""),
        },
    )


@router.post("/{token}/accept", status_code=status.HTTP_200_OK, response_model=None)
async def accept_invitation(
    request: Request,
    bg: BackgroundTasks,
    token: uuid.UUID,
    current_user: CurrentUser,
    rls_session: RlsSession,
    admin_repo: AdminOrgRepo,
    rls_repo: RlsOrgRepo,
):
    # Resolve current invitation state (no membership required)
    invitation = await admin_repo.get_invitation_by_token(token)
    if invitation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
        )

    if invitation["status"] == "accepted":
        # Idempotent: already accepted — resolve org slug and redirect
        org = await rls_repo.get(invitation["org_id"])
        slug = org.handle if org else ""
        redirect_url = f"/{slug}/dashboard"
        if wants_json(request):
            return JSONResponse({"redirect": redirect_url})
        return RedirectResponse(url=redirect_url, status_code=303)

    if invitation["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
        )

    # Check that the logged-in user's email matches the invitation
    if current_user.email.lower() != invitation["email"].lower():
        org = await rls_repo.get(invitation["org_id"])
        org_name = org.name if org else ""
        if wants_json(request):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="this invitation was sent to a different email address",
            )
        return templates.TemplateResponse(
            request,
            "invitations/accept.html",
            {
                "state": "wrong_email",
                "token": str(token),
                "org_name": org_name,
                "email": invitation["email"],
            },
            status_code=403,
        )

    # Call SECURITY DEFINER function via RLS session so auth.uid() is set from the JWT
    try:
        await rls_repo.accept_org_invitation(token)
    except DBAPIError as exc:
        if getattr(exc.orig, "sqlstate", None) == "P0404":
            if wants_json(request):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="invitation not found or already used",
                ) from exc
            return templates.TemplateResponse(
                request,
                "invitations/accept.html",
                {"state": "invalid", "token": str(token), "org_name": "", "email": ""},
                status_code=404,
            )
        log.exception("invitation.accept_error")
        raise

    org = await rls_repo.get(invitation["org_id"])
    slug = org.handle if org else ""
    record_audit_event(
        bg,
        level="info",
        event="org.member_joined",
        user_id=current_user.id,
        org_id=str(invitation["org_id"]),
    )
    redirect_url = f"/{slug}/dashboard"
    if wants_json(request):
        return JSONResponse({"redirect": redirect_url})
    return RedirectResponse(url=redirect_url, status_code=303)
