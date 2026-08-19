import uuid
from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.exc import DBAPIError

from apps.auth.contract.current import CurrentUser, OptionalCurrentUser, RlsSession
from apps.organizations.contract.events import MemberJoined
from apps.organizations.domain.models import InvitationRead, InvitationStatus
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.events.bus import events
from apps.shared.http import wants_json
from apps.shared.http.templates import templates
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.supabase import auth_user_exists

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/invitations", tags=["invitations"])

_NOT_FOUND_DETAIL = "invitation not found or already used"


async def _get_admin_org_repo(admin_session: AdminSession) -> OrganizationRepository:
    return OrganizationRepository(admin_session)


async def _get_rls_org_repo(rls_session: RlsSession) -> OrganizationRepository:
    return OrganizationRepository(rls_session)


AdminOrgRepo = Annotated[OrganizationRepository, Depends(_get_admin_org_repo)]
RlsOrgRepo = Annotated[OrganizationRepository, Depends(_get_rls_org_repo)]


async def _dashboard_redirect(request, rls_repo, org_id):
    org = await rls_repo.get(org_id)
    url = f"/{org.handle if org else ''}/dashboard"
    return (
        JSONResponse({"redirect": url})
        if wants_json(request)
        else RedirectResponse(url, status_code=303)
    )


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
                detail=_NOT_FOUND_DETAIL,
            )
        if invitation["status"] == "revoked":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=_NOT_FOUND_DETAIL,
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
    token: uuid.UUID,
    current_user: CurrentUser,
    rls_session: RlsSession,
    admin_repo: AdminOrgRepo,
    rls_repo: RlsOrgRepo,
):
    # Read on the admin repo: accepting is exactly what the caller has no membership for yet.
    invitation = await admin_repo.get_invitation_by_token(token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    if invitation["status"] == "accepted":
        return await _dashboard_redirect(request, rls_repo, invitation["org_id"])  # idempotent

    if invitation["status"] != "pending":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=_NOT_FOUND_DETAIL)

    if current_user.email.lower() != invitation["email"].lower():
        org = await rls_repo.get(invitation["org_id"])
        org_name = org.name if org else ""
        log.warning(
            "organizations.invitation_email_mismatch",
            user_id=str(current_user.id),
            org_id=str(invitation["org_id"]),
            invited=invitation["email"],
        )
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
                    detail=_NOT_FOUND_DETAIL,
                ) from exc
            return templates.TemplateResponse(
                request,
                "invitations/accept.html",
                {"state": "invalid", "token": str(token), "org_name": "", "email": ""},
                status_code=404,
            )
        log.exception("invitation.accept_error")
        raise

    await events.emit(
        MemberJoined(user_id=current_user.id, org_id=invitation["org_id"]), rls_session
    )
    return await _dashboard_redirect(request, rls_repo, invitation["org_id"])
