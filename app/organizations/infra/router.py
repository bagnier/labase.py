import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, Response, status
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.session import get_rls_session
from app.auth.infra.security import get_current_user
from app.organizations.domain.models import OrgRole, OrganizationRead
from app.organizations.infra.context import get_current_org, set_active_org_cookie
from app.organizations.infra.repository import OrganizationRepository
from app.shared.database import get_service_session

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> list[OrganizationRead]:
    repo = OrganizationRepository(session)
    orgs = await repo.list_for_user(uuid.UUID(current_user.id))
    return [OrganizationRead.model_validate(o) for o in orgs]


class RenameOrgBody(BaseModel):
    name: str


@router.patch("/{org_id}")
async def rename_organization(
    org_id: uuid.UUID,
    body: RenameOrgBody,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service_session: AsyncSession = Depends(get_service_session),
) -> JSONResponse:
    repo = OrganizationRepository(service_session)
    membership = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if membership is None or membership.role not in (OrgRole.owner, OrgRole.admin):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await repo.rename(org, body.name)
    return JSONResponse(OrganizationRead.model_validate(org).model_dump(mode="json"))


@router.post("/switch", response_class=HTMLResponse)
async def switch_org(
    response: Response,
    org_id: uuid.UUID = Form(...),
    current_org: uuid.UUID = Depends(get_current_org),
) -> Response:
    set_active_org_cookie(response, org_id)
    response.headers["HX-Refresh"] = "true"
    return response
