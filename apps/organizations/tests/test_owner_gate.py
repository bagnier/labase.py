import uuid

import pytest
from fastapi import HTTPException

from apps.organizations.domain.models import Membership, OrgRole
from apps.organizations.infra.context import require_current_owner


def _membership(role: OrgRole) -> Membership:
    return Membership(org_id=uuid.uuid4(), auth_user_id=uuid.uuid4(), role=role)


@pytest.mark.asyncio
async def test_require_current_owner_allows_owner():
    membership = _membership(OrgRole.owner)
    assert await require_current_owner(membership=membership) is membership


@pytest.mark.asyncio
async def test_require_current_owner_forbids_member():
    with pytest.raises(HTTPException) as exc:
        await require_current_owner(membership=_membership(OrgRole.member))
    assert exc.value.status_code == 403
