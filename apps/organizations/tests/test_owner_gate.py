import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException, Request

from apps.organizations.domain.models import Membership, OrgRole
from apps.organizations.infra.context import require_current_owner


def _membership(role: OrgRole) -> Membership:
    return Membership(org_id=uuid.uuid4(), auth_user_id=uuid.uuid4(), role=role)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [], "client": None})


@pytest.mark.asyncio
async def test_require_current_owner_allows_owner():
    membership = _membership(OrgRole.owner)
    result = await require_current_owner(
        request=_request(), bg=BackgroundTasks(), membership=membership
    )
    assert result is membership


@pytest.mark.asyncio
async def test_require_current_owner_forbids_member():
    with pytest.raises(HTTPException) as exc:
        await require_current_owner(
            request=_request(), bg=BackgroundTasks(), membership=_membership(OrgRole.member)
        )
    assert exc.value.status_code == 403
