"""Granting admin to an account that is already admin changes nothing — only an effective
change is a fact. Driven by calling the handlers directly with mocks."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from apps.auth.contract.user import AuthenticatedUser
from apps.console.domain.models import AdminFlag, AdminGrant
from apps.console.infra.router import add_admin, update_admin


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/console/admins",
        "headers": [],
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_granting_an_already_admin_account_emits_no_fact():
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="root@test.local")
    session = MagicMock()

    with (
        patch(
            "apps.console.infra.router.find_user_id_by_email", AsyncMock(return_value=uuid.uuid4())
        ),
        patch(
            "apps.console.infra.router.admins.grant_admin",
            AsyncMock(return_value=([], False)),
        ),
        patch("apps.console.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await add_admin(_request(), AdminGrant(email="bob@test.local"), current_user, session)

    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_granting_a_new_admin_emits_the_fact():
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="root@test.local")
    session = MagicMock()

    with (
        patch(
            "apps.console.infra.router.find_user_id_by_email", AsyncMock(return_value=uuid.uuid4())
        ),
        patch(
            "apps.console.infra.router.admins.grant_admin",
            AsyncMock(return_value=([], True)),
        ),
        patch("apps.console.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await add_admin(_request(), AdminGrant(email="bob@test.local"), current_user, session)

    emit.assert_awaited_once()


@pytest.mark.asyncio
async def test_setting_admin_to_its_current_value_emits_no_fact():
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="root@test.local")
    session = MagicMock()

    with (
        patch(
            "apps.console.infra.router.find_user_id_by_email", AsyncMock(return_value=uuid.uuid4())
        ),
        patch(
            "apps.console.infra.router.admins.set_admin",
            AsyncMock(return_value=([], False)),
        ),
        patch("apps.console.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await update_admin(
            _request(), "bob@test.local", AdminFlag(is_admin=True), current_user, session
        )

    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_changing_admin_status_emits_the_fact():
    current_user = AuthenticatedUser(id=uuid.uuid4(), email="root@test.local")
    session = MagicMock()

    with (
        patch(
            "apps.console.infra.router.find_user_id_by_email", AsyncMock(return_value=uuid.uuid4())
        ),
        patch(
            "apps.console.infra.router.admins.set_admin",
            AsyncMock(return_value=([], True)),
        ),
        patch("apps.console.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await update_admin(
            _request(), "bob@test.local", AdminFlag(is_admin=True), current_user, session
        )

    emit.assert_awaited_once()
