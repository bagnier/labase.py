from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from supabase_auth.errors import AuthApiError

from apps.auth.contract.events import UserCreated, UserDeleted
from apps.auth.domain.service import (
    _is_first_sign_in,
    login,
    logout,
    refresh_session,
    register,
)
from apps.auth.tests.given_helpers import delete_user, find_users
from apps.shared.events import BusinessEvent
from apps.shared.persistence.supabase import get_admin_supabase


@pytest.mark.asyncio
async def test_login_valid_credentials_returns_access_and_refresh_tokens(test_user):
    email, password = test_user
    tokens = await login(email, password)
    assert tokens.access_token
    assert tokens.refresh_token


@pytest.mark.asyncio
async def test_login_wrong_password_raises_auth_error(test_user):
    email, _ = test_user
    with pytest.raises(AuthApiError):
        await login(email, "wrong-password")


@pytest.mark.asyncio
async def test_login_unknown_email_raises_auth_error():
    with pytest.raises(AuthApiError):
        await login("nobody@test.local", "whatever")


@pytest.mark.asyncio
async def test_register_new_email_creates_user_in_supabase():
    email = f"{uuid4()}@test.local"
    await register(email, "Test1234!")

    users = find_users(email)
    assert users, f"User {email!r} not found in Supabase after register"
    delete_user(users[0].id)


@pytest.mark.asyncio
async def test_logout_authenticated_session_does_not_raise(test_user):
    email, password = test_user
    tokens = await login(email, password)
    await logout(tokens.access_token)


@pytest.mark.asyncio
async def test_register_existing_email_raises(test_user):
    email, password = test_user
    with pytest.raises(AuthApiError):
        await register(email, password)


@pytest.mark.asyncio
async def test_login_returns_token_valid_for_get_user(test_user):
    email, password = test_user
    tokens = await login(email, password)
    response = get_admin_supabase().auth.get_user(tokens.access_token)
    assert response is not None
    user = response.user
    assert user is not None
    assert user.email == email


@pytest.mark.asyncio
async def test_logout_invalidates_token(test_user):
    email, password = test_user
    tokens = await login(email, password)
    await logout(tokens.access_token)
    with pytest.raises(AuthApiError):
        get_admin_supabase().auth.get_user(tokens.access_token)


@pytest.mark.asyncio
async def test_login_session_none_raises_value_error():
    fake_auth = MagicMock()
    fake_auth.session = None
    fake_supabase = MagicMock()
    fake_supabase.auth.sign_in_with_password = AsyncMock(return_value=fake_auth)
    with (
        patch("apps.auth.domain.service.get_user_supabase", AsyncMock(return_value=fake_supabase)),
        pytest.raises(ValueError, match="No session returned"),
    ):
        await login("a@test.local", "pw")


@pytest.mark.asyncio
async def test_logout_network_error_does_not_raise():
    with patch("apps.auth.domain.service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = OSError("network down")
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
        await logout("some-token")  # must not raise


@pytest.mark.asyncio
async def test_refresh_session_none_raises_value_error():
    fake_auth = MagicMock()
    fake_auth.session = None
    fake_supabase = MagicMock()
    fake_supabase.auth.refresh_session = AsyncMock(return_value=fake_auth)
    with (
        patch("apps.auth.domain.service.get_user_supabase", AsyncMock(return_value=fake_supabase)),
        pytest.raises(ValueError, match="Refresh failed"),
    ):
        await refresh_session("old-refresh-token")


def test_user_created_is_a_persisted_business_event():
    actor = uuid4()
    event = UserCreated(actor_id=actor, entity_id="u1", email="a@b.c")

    assert isinstance(event, BusinessEvent)  # persisted on the trail like any fact
    assert event.kind == "auth.user_created"  # distinct from the sign-in (Login) events
    assert event.actor_id == actor  # the new user acts
    assert event.email == "a@b.c"
    assert not hasattr(event, "access_token")  # a token is never persisted


def test_is_first_sign_in_detects_a_brand_new_oauth_user():
    # GoTrue stamps created_at and last_sign_in_at in the same sign-up — milliseconds apart, and
    # last carries nanosecond precision + Z. That is a genuine first sign-in.
    assert _is_first_sign_in(
        {
            "created_at": "2026-07-22T09:10:08.33665Z",
            "last_sign_in_at": "2026-07-22T09:10:08.358220884Z",
        }
    )
    # A returning user signed up long before this sign-in.
    assert not _is_first_sign_in(
        {"created_at": "2026-01-01T00:00:00Z", "last_sign_in_at": "2026-07-22T09:10:08Z"}
    )
    # No sign-in recorded yet → treat as new; empty payload → not new (nothing to provision).
    assert _is_first_sign_in({"created_at": "2026-07-22T09:10:08Z", "last_sign_in_at": None})
    assert not _is_first_sign_in({})


def test_user_deleted_is_a_persisted_business_event():
    event = UserDeleted(actor_id=uuid4(), entity_id="victim1")

    assert isinstance(event, BusinessEvent)
    assert event.kind == "auth.user_deleted"
    assert event.entity_id == "victim1"  # the removed user — forget consumers key on it
    assert not hasattr(event, "session")  # no live session travels on a frozen fact
