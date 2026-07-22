from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from supabase_auth.errors import AuthApiError

from apps.auth.application import register_user
from apps.auth.domain.service import login, logout, refresh_session, register
from apps.auth.tests.given_helpers import delete_user, find_users
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
    from apps.auth.contract.events import UserCreated
    from apps.shared.events import BusinessEvent, event_class_for

    event = UserCreated(actor_id="u1", entity_id="u1", email="a@b.c")

    assert isinstance(event, BusinessEvent)  # persisted on the trail like any fact
    assert UserCreated.kind == "auth.user_created"  # distinct from the sign-in (Login) events
    assert event_class_for("auth.user_created") is UserCreated  # the tailer can reconstruct it
    assert event.actor_id == "u1"  # the new user acts
    assert event.email == "a@b.c"
    assert not hasattr(event, "access_token")  # a token is never persisted


def test_user_deleted_is_a_persisted_business_event():
    from apps.auth.contract.events import UserDeleted
    from apps.shared.events import BusinessEvent, event_class_for

    event = UserDeleted(actor_id="admin1", entity_id="victim1")

    assert isinstance(event, BusinessEvent)
    assert UserDeleted.kind == "auth.user_deleted"
    assert event_class_for("auth.user_deleted") is UserDeleted
    assert event.entity_id == "victim1"  # the removed user — forget consumers key on it
    assert not hasattr(event, "session")  # no live session travels on a frozen fact


@pytest.mark.asyncio
async def test_register_user_compensates_when_org_creation_fails():
    from apps.auth.domain.service import RegisterResult

    fake_user_id = str(uuid4())
    fake_result = RegisterResult(user_id=fake_user_id, access_token="tok")
    fake_admin = MagicMock()
    fake_admin.auth.admin.delete_user = MagicMock()

    # Org creation is the org context reacting to UserCreated on the bus; a failure there
    # must delete the just-created auth user so no orphan account survives.
    with (
        patch("apps.auth.application.register", AsyncMock(return_value=fake_result)),
        patch(
            "apps.auth.application.events.emit",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch("apps.auth.application.get_admin_supabase", return_value=fake_admin),
        pytest.raises(RuntimeError),
    ):
        await register_user("x@test.local", "pw")

    fake_admin.auth.admin.delete_user.assert_called_once_with(fake_user_id)
