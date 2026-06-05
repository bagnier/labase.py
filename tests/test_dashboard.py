import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_dashboard_requires_auth(client: AsyncClient) -> None:
    r = await client.get("/dashboard")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_root_redirects(client: AsyncClient) -> None:
    r = await client.get("/")
    assert r.status_code == 307
    assert r.headers["location"] == "/dashboard"
