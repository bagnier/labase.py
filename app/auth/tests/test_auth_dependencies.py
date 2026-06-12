from unittest.mock import patch

import jwt
import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.domain.service import AuthTokens, login
from app.auth.infra.security import get_current_user
from app.main import app as main_app

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
            "app.auth.infra.security._decode",
            side_effect=[jwt.ExpiredSignatureError, {"sub": "user-id", "email": email}],
        ),
        patch("app.auth.infra.security.refresh_session", return_value=fake_new_tokens),
    ):
        response = await client.get("/me")

    assert response.status_code == 200
    assert response.json()["id"] == "user-id"
    assert "access_token" in response.cookies
    assert "refresh_token" in response.cookies


@pytest.mark.asyncio
async def test_expired_token_without_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")

    with patch("app.auth.infra.security._decode", side_effect=jwt.ExpiredSignatureError):
        response = await client.get("/me")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_profile_browser_redirect_to_login_when_unauthenticated():
    async with AsyncClient(transport=ASGITransport(app=main_app), base_url="http://test") as c:
        response = await c.get(
            "/profile",
            headers={"Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.headers["location"] == "/auth/login"


@pytest.mark.asyncio
async def test_profile_api_client_still_gets_401_when_unauthenticated():
    async with AsyncClient(transport=ASGITransport(app=main_app), base_url="http://test") as c:
        response = await c.get("/profile", follow_redirects=False)
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_expired_token_with_invalid_refresh_returns_401(client):
    client.cookies.set("access_token", "expired.token.value")
    client.cookies.set("refresh_token", "invalid.refresh.token")

    with (
        patch("app.auth.infra.security._decode", side_effect=jwt.ExpiredSignatureError),
        patch("app.auth.infra.security.refresh_session", side_effect=ValueError("Refresh failed")),
    ):
        response = await client.get("/me")

    assert response.status_code == 401
