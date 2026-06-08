import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.auth.domain.service import login
from app.auth.infra.dependencies import get_current_user

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
async def test_valid_token_returns_user(client, test_user):
    email, password = test_user
    tokens = login(email, password)
    client.cookies.set("access_token", tokens.access_token)
    response = await client.get("/me")
    assert response.status_code == 200
    assert response.json()["id"]
