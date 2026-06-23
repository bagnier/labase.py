from unittest.mock import MagicMock, patch

import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient
from supabase_auth.errors import AuthApiError

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, login
from apps.auth.infra.security import get_current_user

_app = FastAPI()


@_app.get("/me")
async def me(user=Depends(get_current_user)):
    return {"id": str(user.id)}


@pytest_asyncio.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_no_cookie_returns_401(client):
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_invalid_token_returns_401(client):
    client.cookies.set("access_token", "garbage")
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_signature_returns_401(client):
    # A well-formed JWT structure but signed with a different key
    client.cookies.set(
        "access_token",
        "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIxMjMiLCJhdWQiOiJhdXRoZW50aWNhdGVkIn0"
        ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    response = await client.get("/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_valid_token_returns_user(client, test_user):
    email, password = test_user
    tokens = await login(email, password)
    client.cookies.set("access_token", tokens.access_token)
    response = await client.get("/me")
    assert response.status_code == 200
    assert response.json()["id"]


@pytest.mark.asyncio
async def test_expired_token_with_valid_refresh_returns_200_and_sets_new_cookies(client, test_user):
    email, password = test_user
    real_tokens = await login(email, password)
    fake_new_tokens = AuthTokens(
        access_token=real_tokens.access_token, refresh_token=real_tokens.refresh_token
    )

    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", real_tokens.refresh_token)

    with (
        patch(
            "apps.auth.infra.security.decode_jwt",
            side_effect=[jwt.ExpiredSignatureError, {"sub": "user-id", "email": email}],
        ),
        patch("apps.auth.infra.security.refresh_session", return_value=fake_new_tokens),
    ):
        response = await client.get("/me")

    assert response.status_code == 200
    assert response.json()["id"] == "user-id"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_expired_token_without_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")

    with patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError):
        response = await client.get("/me")

    assert response.status_code == 401


def test_profile_browser_redirect_to_login_when_unauthenticated(driver):
    response = driver.client().get(
        "/profile",
        headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login?next=/profile"


def test_profile_api_client_gets_401_with_json_accept(driver):
    response = driver.client().get(
        "/profile",
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_with_invalid_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "invalid.refresh.token")

    with (
        patch("apps.auth.infra.security.decode_jwt", side_effect=jwt.ExpiredSignatureError),
        patch("apps.auth.infra.security.refresh_session", side_effect=ValueError("Refresh failed")),
    ):
        response = await client.get("/me")

    assert response.status_code == 401


def test_login_unexpected_exception_returns_503(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=RuntimeError("unexpected")):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 503
    assert "system error" in response.text.lower()


def test_login_email_not_confirmed_returns_401_with_message(driver):
    err = AuthApiError("Email not confirmed", 400, "email_not_confirmed")
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=err):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 401
    assert "verify your email" in response.text.lower()


def test_login_wrong_password_returns_401_with_generic_message(driver):
    err = AuthApiError("Invalid login credentials", 400, "invalid_credentials")
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.login", side_effect=err):
        response = driver.client().post("/auth/login", data=creds)
    assert response.status_code == 401
    assert "invalid email or password" in response.text.lower()


def test_register_unexpected_exception_returns_400(driver):
    creds = {"email": "x@test.local", "password": "pw"}
    with patch("apps.auth.infra.router.register_user", side_effect=RuntimeError("unexpected")):
        response = driver.client().post("/auth/register", data=creds)
    assert response.status_code == 400
    assert "unexpected error" in response.text.lower()


@pytest.mark.asyncio
async def test_get_rls_session_sets_and_clears_rls_context():
    from apps.auth.infra.session import get_rls_session

    fake_user = AuthenticatedUser(id="00000000-0000-0000-0000-000000000001", email="t@test.local")
    fake_session = MagicMock()

    set_calls = []
    clear_calls = []

    async def mock_set(session, uid):
        set_calls.append(uid)

    async def mock_clear(session):
        clear_calls.append(True)

    with (
        patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set),
        patch("apps.auth.infra.session.clear_rls_context", side_effect=mock_clear),
    ):
        gen = get_rls_session(current_user=fake_user, session=fake_session)
        session = await gen.__anext__()
        assert session is fake_session
        assert set_calls, "set_rls_context should have been called"
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
        assert clear_calls, "clear_rls_context should have been called in finally block"


@pytest.mark.asyncio
async def test_get_rls_session_clears_rls_even_when_clear_raises():
    from apps.auth.infra.session import get_rls_session

    fake_user = AuthenticatedUser(id="00000000-0000-0000-0000-000000000001", email="t@test.local")
    fake_session = MagicMock()

    async def mock_set(session, uid):
        pass

    async def mock_clear_raises(session):
        raise RuntimeError("db gone")

    with (
        patch("apps.auth.infra.session.set_rls_context", side_effect=mock_set),
        patch("apps.auth.infra.session.clear_rls_context", side_effect=mock_clear_raises),
    ):
        gen = get_rls_session(current_user=fake_user, session=fake_session)
        await gen.__anext__()
        # clear_rls_context raises but the warning is swallowed — no exception should propagate
        with pytest.raises(StopAsyncIteration):
            await gen.__anext__()
