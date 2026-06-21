from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from supabase_auth.errors import AuthApiError

from app.auth.application import register_user
from app.auth.domain.service import login, logout, refresh_session, register
from app.auth.tests.given_helpers import delete_user, find_users
from app.shared.persistence.supabase import get_admin_supabase


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
        patch("app.auth.domain.service.get_user_supabase", AsyncMock(return_value=fake_supabase)),
        pytest.raises(ValueError, match="No session returned"),
    ):
        await login("a@test.local", "pw")


@pytest.mark.asyncio
async def test_logout_network_error_does_not_raise():
    with patch("app.auth.domain.service.httpx.AsyncClient") as mock_client_cls:
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
        patch("app.auth.domain.service.get_user_supabase", AsyncMock(return_value=fake_supabase)),
        pytest.raises(ValueError, match="Refresh failed"),
    ):
        await refresh_session("old-refresh-token")


@pytest.mark.asyncio
async def test_register_user_compensates_when_org_creation_fails():
    from app.auth.domain.service import RegisterResult

    fake_user_id = str(uuid4())
    fake_result = RegisterResult(user_id=fake_user_id, access_token="tok")
    fake_admin = MagicMock()
    fake_admin.auth.admin.delete_user = MagicMock()

    # Org creation is the org context reacting to UserCreated on the bus; a failure there
    # must delete the just-created auth user so no orphan account survives.
    with (
        patch("app.auth.application.register", AsyncMock(return_value=fake_result)),
        patch(
            "app.auth.application.host.events.emit",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch("app.auth.application.get_admin_supabase", return_value=fake_admin),
        pytest.raises(RuntimeError),
    ):
        await register_user("x@test.local", "pw")

    fake_admin.auth.admin.delete_user.assert_called_once_with(fake_user_id)
