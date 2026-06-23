import uuid

from fastapi import Depends, HTTPException, Request, status

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.slug_registry import is_reserved


async def get_current_org(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
) -> uuid.UUID:
    """Resolve org from {org_handle} path parameter."""
    user_uuid = uuid.UUID(current_user.id)
    repo = OrganizationRepository(session)

    slug = request.path_params.get("org_handle")
    if slug:
        # A reserved slug (e.g. /console) must never resolve as an org handle. If routing ever
        # lets one reach here, fail as 404 — never confirm the reserved surface exists.
        if is_reserved(slug):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        # Single join: org by slug that the current user is a member of
        org = await repo.get_by_handle_for_user(slug, user_uuid)
        if org is not None:
            return org.id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Organisation not found or access denied"
        )

    # Fallback for routes not under /{org_handle}: use first org
    org = await repo.get_first_for_user(user_uuid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organization found")
    return org.id


async def get_current_org_model(
    session: RlsSession,
    org_id: uuid.UUID = Depends(get_current_org),
) -> Organization:
    org = await OrganizationRepository(session).get(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organisation not found")
    return org


async def get_current_membership(
    current_user: CurrentUser,
    session: RlsSession,
    org_id: uuid.UUID = Depends(get_current_org),
) -> Membership:
    user_uuid = uuid.UUID(current_user.id)
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, user_uuid)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member")
    return membership


async def get_membership_by_org_id(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
) -> Membership:
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return membership


async def require_owner(
    membership: Membership = Depends(get_membership_by_org_id),
) -> Membership:
    """Owner gate for routes with an ``{org_id}`` path parameter (JSON API)."""
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return membership


async def require_current_owner(
    membership: Membership = Depends(get_current_membership),
) -> Membership:
    """Owner gate for ``/{org_handle}/...`` routes (resolves the org from the slug)."""
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return membership
