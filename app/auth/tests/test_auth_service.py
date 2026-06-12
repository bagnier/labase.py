from uuid import uuid4

import httpx
import pytest
from supabase_auth.errors import AuthApiError

from app.auth.domain.service import login, logout, register
from app.auth.tests.admin_helpers import admin_headers, delete_user
from app.shared.config import get_settings
from app.shared.persistence.supabase import get_supabase


def test_login_valid_credentials_returns_access_and_refresh_tokens(test_user):
    email, password = test_user
    tokens = login(email, password)
    assert tokens.access_token
    assert tokens.refresh_token


def test_login_wrong_password_raises_auth_error(test_user):
    email, _ = test_user
    with pytest.raises(AuthApiError):
        login(email, "wrong-password")


def test_login_unknown_email_raises_auth_error():
    with pytest.raises(AuthApiError):
        login("nobody@test.local", "whatever")


def test_register_new_email_creates_user_in_supabase():
    email = f"{uuid4()}@test.local"
    register(email, "Test1234!")

    r = httpx.get(
        f"{get_settings().supabase_url}/auth/v1/admin/users",
        headers=admin_headers(),
        params={"email": email},
    )
    r.raise_for_status()
    users = r.json().get("users", [])

    assert any(u["email"] == email for u in users)
    uid = next(u["id"] for u in users if u["email"] == email)
    delete_user(uid)


def test_logout_authenticated_session_does_not_raise(test_user):
    email, password = test_user
    login(email, password)
    logout()


def test_register_existing_email_raises(test_user):
    email, password = test_user
    with pytest.raises(Exception):
        register(email, password)


def test_login_returns_token_valid_for_get_user(test_user):
    email, password = test_user
    tokens = login(email, password)
    response = get_supabase().auth.get_user(tokens.access_token)
    assert response is not None
    user = response.user
    assert user is not None
    assert user.email == email


def test_logout_invalidates_token(test_user):
    email, password = test_user
    tokens = login(email, password)
    logout()
    with pytest.raises(Exception):
        get_supabase().auth.get_user(tokens.access_token)
