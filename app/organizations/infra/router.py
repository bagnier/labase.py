import uuid

from fastapi import APIRouter, Depends, Form, Response
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.session import get_rls_session
from app.auth.infra.security import get_current_user
from app.organizations.domain.models import OrganizationRead
from app.organizations.infra.context import get_current_org, set_active_org_cookie
from app.organizations.infra.repository import OrganizationRepository

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> list[OrganizationRead]:
    repo = OrganizationRepository(session)
    orgs = await repo.list_for_user(uuid.UUID(current_user.id))
    return [OrganizationRead.model_validate(o) for o in orgs]


@router.post("/switch", response_class=HTMLResponse)
async def switch_org(
    response: Response,
    org_id: uuid.UUID = Form(...),
    current_org: uuid.UUID = Depends(get_current_org),
) -> Response:
    set_active_org_cookie(response, org_id)
    response.headers["HX-Refresh"] = "true"
    return response
