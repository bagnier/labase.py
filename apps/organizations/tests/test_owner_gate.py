import uuid

import pytest
from fastapi import HTTPException
from structlog.testing import capture_logs

from apps.organizations.domain.models import Membership, OrgRole
from apps.organizations.infra.context import require_current_owner


def _membership(role: OrgRole) -> Membership:
    return Membership(org_id=uuid.uuid7(), user_id=uuid.uuid7(), role=role)


@pytest.mark.asyncio
async def test_require_current_owner_allows_owner():
    membership = _membership(OrgRole.owner)
    result = await require_current_owner(membership=membership)
    assert result is membership


@pytest.mark.asyncio
async def test_require_current_owner_forbids_member():
    with pytest.raises(HTTPException) as exc:
        await require_current_owner(membership=_membership(OrgRole.member))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_current_owner_forbids_member_without_a_line_of_its_own():
    """``request.finished`` already reports this 403 with the user, org and path bound as
    contextvars, plus the detail via ``note_rejection`` — a line here would only restate it
    under a different name."""
    with capture_logs() as logs, pytest.raises(HTTPException):
        await require_current_owner(membership=_membership(OrgRole.member))

    assert logs == []
