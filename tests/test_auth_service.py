from uuid import uuid4

import httpx
import pytest
from supabase_auth.errors import AuthApiError

from app.auth.domain.service import login, logout, register
from app.shared.config import get_settings
from app.shared.supabase_client import get_supabase


def _admin_headers() -> dict:
    key = get_settings().supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def _create_user(email: str, password: str) -> str:
    r = httpx.post(
        f"{get_settings().supabase_url}/auth/v1/admin/users",
        headers=_admin_headers(),
        json={"email": email, "password": password, "email_confirm": True},
    )
    r.raise_for_status()
    return r.json()["id"]


def _delete_user(uid: str) -> None:
    r = httpx.delete(
        f"{get_settings().supabase_url}/auth/v1/admin/users/{uid}",
        headers=_admin_headers(),
    )
    r.raise_for_status()


@pytest.fixture()
def test_user():
    email = f"{uuid4()}@test.local"
    password = "Test1234!"
    uid = _create_user(email, password)
    yield email, password
    _delete_user(uid)


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
        headers=_admin_headers(),
        params={"email": email},
    )
    r.raise_for_status()
    users = r.json().get("users", [])

    assert any(u["email"] == email for u in users)
    uid = next(u["id"] for u in users if u["email"] == email)
    _delete_user(uid)


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
    assert response.user is not None
    assert response.user.email == email


def test_logout_invalidates_token(test_user):
    email, password = test_user
    tokens = login(email, password)
    logout()
    with pytest.raises(Exception):
        get_supabase().auth.get_user(tokens.access_token)
