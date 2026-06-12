import uuid

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import text

from app.organizations.domain.models import InvitationRead, InvitationStatus
from app.organizations.infra.repository import OrganizationRepository
from app.shared.dependencies import AdminSession, CurrentUser, RlsSession
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event

log = structlog.get_logger("labase.organizations.invitations")

router = APIRouter(prefix="/invitations", tags=["invitations"])


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


@router.get("/{token}", response_model=None)
async def get_invitation(
    request: Request,
    token: uuid.UUID,
    admin_session: AdminSession,
):
    result = await admin_session.execute(
        text("SELECT * FROM public.get_invitation_by_token(:token)"),
        {"token": str(token)},
    )
    row = result.mappings().first()

    if _wants_json(request):
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found or already used",
            )
        inv = dict(row)
        if inv["status"] == "revoked":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found or already used",
            )
        return InvitationRead(
            id=inv["id"],
            org_id=inv["org_id"],
            email=inv["email"],
            role=inv["role"],
            token=inv["token"],
            status=InvitationStatus(inv["status"]),
            created_at=inv["created_at"],
        )

    # HTML response
    if row is None:
        return templates.TemplateResponse(
            request,
            "invitations/accept.html",
            {"state": "invalid", "token": str(token), "org_name": "", "email": ""},
            status_code=404,
        )
    inv = dict(row)
    repo = OrganizationRepository(admin_session)
    org = await repo.get_by_id(inv["org_id"])
    org_name = org.name if org else ""
    if inv["status"] == "accepted":
        state = "already_accepted"
    elif inv["status"] == "revoked":
        state = "invalid"
    else:
        state = "valid"
    return templates.TemplateResponse(
        request,
        "invitations/accept.html",
        {
            "state": state,
            "token": str(token),
            "org_name": org_name,
            "email": inv.get("email", ""),
        },
    )


@router.post("/{token}/accept", status_code=status.HTTP_200_OK, response_model=None)
async def accept_invitation(
    request: Request,
    bg: BackgroundTasks,
    token: uuid.UUID,
    current_user: CurrentUser,
    rls_session: RlsSession,
    admin_session: AdminSession,
):
    # Resolve current invitation state (no membership required)
    inv_result = await admin_session.execute(
        text("SELECT * FROM public.get_invitation_by_token(:token)"),
        {"token": str(token)},
    )
    row = inv_result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
        )

    inv = dict(row)

    if inv["status"] == "accepted":
        # Idempotent: already accepted — resolve org slug and redirect
        repo = OrganizationRepository(rls_session)
        org = await repo.get_by_id(inv["org_id"])
        slug = org.slug if org else ""
        redirect_url = f"/orgs/{slug}/dashboard"
        if _wants_json(request):
            return JSONResponse({"redirect": redirect_url})
        return RedirectResponse(url=redirect_url, status_code=303)

    if inv["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
        )

    # Call SECURITY DEFINER function via RLS session so auth.uid() is set from the JWT
    try:
        await rls_session.execute(
            text("SELECT public.accept_org_invitation(:token)"),
            {"token": str(token)},
        )
        await rls_session.commit()
    except Exception as exc:
        msg = str(exc)
        if "invitation not found or already used" in msg:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
            ) from exc
        log.exception("invitation.accept_error")
        raise

    repo = OrganizationRepository(rls_session)
    org = await repo.get_by_id(inv["org_id"])
    slug = org.slug if org else ""
    record_audit_event(
        bg,
        level="info",
        event="org.member_joined",
        user_id=current_user.id,
        org_id=str(inv["org_id"]),
    )
    redirect_url = f"/orgs/{slug}/dashboard"
    if _wants_json(request):
        return JSONResponse({"redirect": redirect_url})
    return RedirectResponse(url=redirect_url, status_code=303)
