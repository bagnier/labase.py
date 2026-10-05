"""Org dependencies for other contexts: the current org from ``{org_handle}`` (RLS-gated), the
membership, the owner gate, and :func:`app_settings`, which needs the same org resolution.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from apps.auth.contract.current import OptionalCurrentUser, RlsSession
from apps.organizations.domain.models import Membership, Organization
from apps.organizations.domain.models import OrganizationRead as OrganizationRead
from apps.organizations.domain.models import OrgRole as OrgRole
from apps.organizations.infra.context import (
    get_current_membership,
    get_current_org,
    get_current_org_model,
    require_current_owner,
    require_owner,
)
from apps.shared.settings.live import SettingsView, get_settings

CurrentOrg = Annotated[UUID, Depends(get_current_org)]
CurrentOrgModel = Annotated[Organization, Depends(get_current_org_model)]
CurrentMembership = Annotated[Membership, Depends(get_current_membership)]
OwnerMembership = Annotated[Membership, Depends(require_owner)]
CurrentOwnerMembership = Annotated[Membership, Depends(require_current_owner)]


def app_settings(app_name: str) -> Callable[..., Awaitable[SettingsView]]:
    """A dependency giving ``app_name``'s effective settings: under ``/{org_handle}`` for a
    member, with the org's overrides (same guards as ``CurrentOrg``); elsewhere, the server values.

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
