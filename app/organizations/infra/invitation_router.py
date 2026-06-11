import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.auth.infra.session import get_rls_session
from app.organizations.domain.models import InvitationRead, InvitationStatus
from app.organizations.infra.repository import OrganizationRepository
from app.shared.database import get_service_session

router = APIRouter(prefix="/invitations", tags=["invitations"])


@router.get("/{token}", response_model=InvitationRead)
async def get_invitation(
    token: uuid.UUID,
    service_session: AsyncSession = Depends(get_service_session),
) -> InvitationRead:
    result = await service_session.execute(
        text("SELECT * FROM public.get_invitation_by_token(:token)"),
        {"token": str(token)},
    )
    row = result.mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
        )
    inv = dict(row)
    if inv["status"] == "revoked":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found or already used"
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


@router.post("/{token}/accept", status_code=status.HTTP_200_OK)
async def accept_invitation(
    token: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    rls_session: AsyncSession = Depends(get_rls_session),
    service_session: AsyncSession = Depends(get_service_session),
) -> JSONResponse:
    # Resolve current invitation state (no membership required)
    inv_result = await service_session.execute(
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
        return JSONResponse({"redirect": f"/orgs/{slug}/dashboard"})

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
        raise

    repo = OrganizationRepository(rls_session)
    org = await repo.get_by_id(inv["org_id"])
    slug = org.slug if org else ""
    return JSONResponse({"redirect": f"/orgs/{slug}/dashboard"})
