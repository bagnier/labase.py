"""Organizations' public FastAPI dependencies — the current org, membership and settings.

The sanctioned inter-context surface for org scoping: ``CurrentOrg`` resolves the
``{org_handle}`` slug to an org the caller is a member of (RLS-gated), and the
others derive from it (model, membership, owner gate). Other contexts also import
``OrgRole`` / ``Membership`` from here rather than reaching into the domain layer.

:func:`app_settings` lives here too (not in ``apps.shared``, which may not import
contexts): an app's *effective settings for the request* need the very same org
resolution when the request carries one.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from apps.auth.contract.current import OptionalCurrentUser, RlsSession
from apps.organizations.domain.models import Membership as Membership
from apps.organizations.domain.models import Organization
from apps.organizations.domain.models import OrganizationRead as OrganizationRead
from apps.organizations.domain.models import OrgRole as OrgRole
from apps.organizations.infra.context import (
    get_current_membership,
    get_current_org,
    get_current_org_model,
    require_current_owner,
    require_owner,
)
from apps.shared.settings import SettingsView, get_settings

CurrentOrg = Annotated[UUID, Depends(get_current_org)]
CurrentOrgModel = Annotated[Organization, Depends(get_current_org_model)]
CurrentMembership = Annotated[Membership, Depends(get_current_membership)]
OwnerMembership = Annotated[Membership, Depends(require_owner)]
CurrentOwnerMembership = Annotated[Membership, Depends(require_current_owner)]


def app_settings(app_name: str) -> Callable[..., Awaitable[SettingsView]]:
    """The one way a handler reads ``app_name``'s settings: a resolver of its *effective*
    values for the request. Under ``/{org_handle}`` with an authenticated member, server values
    overlaid with that org's console overrides (read through the request's RLS session — same
    403 and reserved-slug guards as ``CurrentOrg``); on any other route (anonymous included),
    the plain server values. No first-org fallback: no org named in the URL means no override
    applies.

    Usage, in an app's ``contract/current.py``::

        TodoSettings = Annotated[SettingsView, Depends(app_settings("todo"))]
    """

    async def _resolve(
        request: Request, user: OptionalCurrentUser, session: RlsSession
    ) -> SettingsView:
        settings = get_settings(app_name)
        if user is None or "org_handle" not in request.path_params:
            return settings.view()
        org_id = await get_current_org(request, user, session)
        return await settings.for_org(session, org_id)

    return _resolve


OrganizationsSettings = Annotated[SettingsView, Depends(app_settings("organizations"))]
