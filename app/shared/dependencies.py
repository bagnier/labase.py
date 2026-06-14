import uuid
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.auth.infra.session import get_rls_session
from app.organizations.domain.models import Membership, Organization
from app.organizations.infra.context import (
    get_current_membership,
    get_current_org,
    get_current_org_model,
    require_owner,
)
from app.shared.persistence.database import get_admin_session

CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
RlsSession = Annotated[AsyncSession, Depends(get_rls_session)]
AdminSession = Annotated[AsyncSession, Depends(get_admin_session)]
CurrentOrg = Annotated[uuid.UUID, Depends(get_current_org)]
CurrentOrgModel = Annotated[Organization, Depends(get_current_org_model)]
CurrentMembership = Annotated[Membership, Depends(get_current_membership)]
OwnerMembership = Annotated[Membership, Depends(require_owner)]
