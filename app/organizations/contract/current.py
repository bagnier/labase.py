"""Organizations' public FastAPI dependencies — the current org and membership.

The sanctioned inter-context surface for org scoping: ``CurrentOrg`` resolves the
``{org_handle}`` slug to an org the caller is a member of (RLS-gated), and the
others derive from it (model, membership, owner gate). Other contexts also import
``OrgRole`` / ``Membership`` from here rather than reaching into the domain layer.
"""

from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.organizations.domain.models import Membership as Membership
from app.organizations.domain.models import Organization
from app.organizations.domain.models import OrgRole as OrgRole
from app.organizations.infra.context import (
    get_current_membership,
    get_current_org,
    get_current_org_model,
    require_current_owner,
    require_owner,
)

CurrentOrg = Annotated[UUID, Depends(get_current_org)]
CurrentOrgModel = Annotated[Organization, Depends(get_current_org_model)]
CurrentMembership = Annotated[Membership, Depends(get_current_membership)]
OwnerMembership = Annotated[Membership, Depends(require_owner)]
CurrentOwnerMembership = Annotated[Membership, Depends(require_current_owner)]
