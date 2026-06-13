from uuid import uuid4

import pytest
from supabase_auth.errors import AuthApiError

from app.auth.domain.service import login, logout, register
from app.auth.tests.admin_helpers import delete_user, find_users
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
