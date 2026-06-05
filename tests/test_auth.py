import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_login_page(client: AsyncClient) -> None:
    r = await client.get("/auth/login")
    assert r.status_code == 200
    assert "Connexion" in r.text


@pytest.mark.asyncio
async def test_register_page(client: AsyncClient) -> None:
    r = await client.get("/auth/register")
    assert r.status_code == 200
    assert "Créer un compte" in r.text


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: AsyncClient) -> None:
    r = await client.post(
        "/auth/login",
        data={"email": "nobody@example.com", "password": "wrong"},
    )
    assert r.status_code == 401
    assert "invalide" in r.text


@pytest.mark.asyncio
async def test_logout(client: AsyncClient) -> None:
    r = await client.post("/auth/logout")
    assert r.status_code == 200
    assert r.headers.get("hx-redirect") == "/auth/login"
