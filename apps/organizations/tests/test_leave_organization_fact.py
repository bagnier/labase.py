"""A racing second `leave` finds the membership already gone — ``remove_member`` deletes 0
rows and returns ``False``. Only what happened is a fact, so that race must journal nothing.
Driven by calling the handler directly with mocks."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from apps.auth.contract.user import AuthenticatedUser
from apps.organizations.infra.router import leave_organization


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "DELETE",
        "path": "/acme/members/me",
        "headers": [],
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


def _repo(*, removed: bool) -> AsyncMock:
    repo = AsyncMock()
    repo.get = AsyncMock(return_value=MagicMock())
    repo.remove_member = AsyncMock(return_value=removed)
    return repo


@pytest.mark.asyncio
async def test_leaving_an_already_gone_membership_emits_no_fact():
    org_id = uuid.uuid4()
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="member@test.local")
    repo = _repo(removed=False)

    with patch("apps.organizations.infra.router.events.emit", AsyncMock()) as emit:
        await leave_organization(_request(), current_user, repo, org_id, MagicMock())

    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_leaving_emits_the_fact_once():
    org_id = uuid.uuid4()
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="member@test.local")
    repo = _repo(removed=True)

    with patch("apps.organizations.infra.router.events.emit", AsyncMock()) as emit:
        await leave_organization(_request(), current_user, repo, org_id, MagicMock())

    emit.assert_awaited_once()
