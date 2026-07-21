"""The invite endpoint canonicalises the email before dedup — otherwise `Foo@x.com`
and `foo@x.com` both pass the pending-invitation check (the accept RPC lower()s, so both
stay redeemable by the same person). Driven by calling the handler directly with mocks."""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException, Request

from apps.auth.contract.current import AuthenticatedUser
from apps.organizations.domain.models import InvitationStatus
from apps.organizations.infra.router import create_invitation


def _json_request(payload: dict) -> Request:
    body = json.dumps(payload).encode()
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/acme/invitations",
        "headers": [(b"content-type", b"application/json"), (b"accept", b"application/json")],
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_invite_dedup_uses_lowercased_email():
    org_id = uuid.uuid4()
    current_user = AuthenticatedUser(id=str(uuid.uuid4()), email="owner@test.local")

    repo = AsyncMock()
    repo.get_membership = AsyncMock(return_value=None)
    repo.list_invitations = AsyncMock(return_value=[])
    # A pending invitation already exists for the canonical address.
    repo.get_invitation_by_email = AsyncMock(return_value=MagicMock())
    repo.create_invitation = AsyncMock()

    settings = MagicMock(max_invitations_per_org=10)
    membership = MagicMock()

    with (
        patch(
            "apps.organizations.infra.router.find_user_id_by_email", AsyncMock(return_value=None)
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await create_invitation(
            _json_request({"email": "  Foo@X.com "}),
            current_user,
            repo,
            org_id,
            membership,
            settings,
        )

    assert exc.value.status_code == 409  # rejected as a duplicate pending invite
    repo.get_invitation_by_email.assert_awaited_once_with(
        org_id, "foo@x.com", InvitationStatus.pending
    )
    repo.create_invitation.assert_not_awaited()  # dedup short-circuited before create
