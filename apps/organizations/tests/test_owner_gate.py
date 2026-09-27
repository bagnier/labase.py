import uuid
from unittest.mock import AsyncMock

import pytest
import structlog
from fastapi import HTTPException
from structlog.testing import capture_logs

from apps.auth.contract.user import AuthenticatedUser
from apps.organizations.domain.models import Membership, OrgRole
from apps.organizations.infra.context import get_membership_by_org_id, require_current_owner
from apps.organizations.infra.repository import OrganizationRepository


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


@pytest.mark.asyncio
async def test_get_membership_by_org_id_binds_org_id_the_way_get_current_org_does(monkeypatch):
    """``require_owner``'s lane (an ``{org_id}`` path param) is the only other place ``org_id``
    must be bound as a contextvar, so its refusals correlate with the Timeline's org filter the
    same way ``require_current_owner``'s lane does."""
    membership = _membership(OrgRole.member)

    async def fake_get_membership(self, org, user):
        return membership

    monkeypatch.setattr(OrganizationRepository, "get_membership", fake_get_membership)
    structlog.contextvars.clear_contextvars()

    try:
        await get_membership_by_org_id(
            org_id=membership.org_id,
            current_user=AuthenticatedUser(id=membership.user_id, email="member@test.local"),
            session=AsyncMock(),
        )
        assert structlog.contextvars.get_contextvars() == {"org_id": str(membership.org_id)}
    finally:
        structlog.contextvars.clear_contextvars()
