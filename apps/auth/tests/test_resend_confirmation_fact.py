"""GoTrue answers the resend-confirmation request the same way for a known and an unknown
address (no enumeration) — but only a known address is where anything happened. Only what
happened is a fact. Driven by calling the handler directly with mocks."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from apps.auth.domain.models import EmailAddress
from apps.auth.infra.router import resend_confirmation_endpoint


def _request() -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/auth/resend-confirmation",
        "headers": [],
        "query_string": b"",
    }

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(scope, receive)


@pytest.mark.asyncio
async def test_resend_confirmation_for_unknown_address_emits_no_fact():
    users_settings = MagicMock(resend_confirmation_enabled=True)
    admin_session = MagicMock()

    with (
        patch("apps.auth.infra.router.find_user_id_by_email", AsyncMock(return_value=None)),
        patch("apps.auth.infra.router.resend_confirmation", AsyncMock()) as resend,
        patch("apps.auth.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await resend_confirmation_endpoint(
            _request(), EmailAddress(email="ghost@example.com"), users_settings, admin_session
        )

    resend.assert_not_awaited()  # nothing to ask GoTrue for an address with no account
    emit.assert_not_awaited()


@pytest.mark.asyncio
async def test_resend_confirmation_for_a_known_address_emits_the_fact():
    users_settings = MagicMock(resend_confirmation_enabled=True)
    admin_session = MagicMock()
    uid = uuid.uuid4()

    with (
        patch("apps.auth.infra.router.find_user_id_by_email", AsyncMock(return_value=uid)),
        patch("apps.auth.infra.router.resend_confirmation", AsyncMock()) as resend,
        patch("apps.auth.infra.router.events.emit", AsyncMock()) as emit,
    ):
        await resend_confirmation_endpoint(
            _request(), EmailAddress(email="bob@example.com"), users_settings, admin_session
        )

    resend.assert_awaited_once()
    emit.assert_awaited_once()
