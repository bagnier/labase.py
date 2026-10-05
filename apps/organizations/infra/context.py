import uuid

import structlog
from fastapi import Depends, HTTPException, Request, status

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.auth.contract.user import AuthenticatedUser
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.integration.slugs import is_reserved


async def get_current_org(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
) -> uuid.UUID:
    """Resolve the request's org and bind ``org_id`` for its logs."""
    org_id = await _resolve_current_org(request, current_user, session)
    structlog.contextvars.bind_contextvars(org_id=str(org_id))
    return org_id


async def _resolve_current_org(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
) -> uuid.UUID:
    user_uuid = current_user.id
    repo = OrganizationRepository(session)

    slug = request.path_params.get("org_handle")
    if slug:
        # A reserved slug never resolves; a 404 confirms nothing.
        if is_reserved(slug):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        org = await repo.get_by_handle_for_user(slug, user_uuid)
        if org is not None:
            _ensure_api_key_scope(current_user, org.id)
            return org.id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Organisation not found or access denied"
        )

    if current_user.api_key_org_id is not None:
        return current_user.api_key_org_id

    # Outside /{org_handle}: the user's first org.
    org = await repo.get_first_for_user(user_uuid)
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No organization found")
    return org.id


def _ensure_api_key_scope(current_user: AuthenticatedUser, org_id: uuid.UUID) -> None:
    """An API key authenticates as its creator but only inside its own organisation."""
    bound = current_user.api_key_org_id
    if bound is not None and org_id != bound:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This API key is not valid for this organisation",
        )


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
    user_uuid = current_user.id
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
    """Owner gate for ``{org_id}`` routes, binding ``org_id`` first so refusals carry it."""
    structlog.contextvars.bind_contextvars(org_id=str(org_id))
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, current_user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return membership


def _gate_owner(membership: Membership) -> Membership:
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return membership


async def require_owner(
    membership: Membership = Depends(get_membership_by_org_id),
) -> Membership:
    return _gate_owner(membership)


async def require_current_owner(
    membership: Membership = Depends(get_current_membership),
) -> Membership:
    return _gate_owner(membership)
