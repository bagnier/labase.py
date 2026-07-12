import uuid

import structlog
from fastapi import Depends, HTTPException, Request, status

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.auth.contract.user import AuthenticatedUser
from apps.organizations.contract.events import OwnershipViolation
from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.bus import bus
from apps.shared.slug_registry import is_reserved


async def get_current_org(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
) -> uuid.UUID:
    """Resolve the request's org, then correlate this request's logs with it — the unified logs
    viewer filters the firehose by org_id (bound once here, at the single resolution point)."""
    org_id = await _resolve_current_org(request, current_user, session)
    structlog.contextvars.bind_contextvars(org_id=str(org_id))
    return org_id


async def _resolve_current_org(
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
            _ensure_api_key_scope(current_user, org.id)
            return org.id
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Organisation not found or access denied"
        )

    # An API-key principal has exactly one organisation: its own.
    if current_user.api_key_org_id is not None:
        return current_user.api_key_org_id

    # Fallback for routes not under /{org_handle}: use first org
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


async def _gate_owner(request: Request, membership: Membership) -> Membership:
    if membership.role != OrgRole.owner:
        # ip rides in from the request contextvars; the persister enriches it at write time.
        await bus.emit(
            OwnershipViolation(
                actor_id=str(membership.auth_user_id),
                org_id=str(membership.org_id),
                path=request.url.path,
            )
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    return membership


async def require_owner(
    request: Request,
    membership: Membership = Depends(get_membership_by_org_id),
) -> Membership:
    """Owner gate for routes with an ``{org_id}`` path parameter (JSON API)."""
    return await _gate_owner(request, membership)


async def require_current_owner(
    request: Request,
    membership: Membership = Depends(get_current_membership),
) -> Membership:
    """Owner gate for ``/{org_handle}/...`` routes (resolves the org from the slug)."""
    return await _gate_owner(request, membership)
