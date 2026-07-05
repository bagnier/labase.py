import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from apps.shared.http.security import csrf_protect


@pytest_asyncio.fixture()
async def csrf_client():
    _app = FastAPI()
    _app.middleware("http")(csrf_protect)

    @_app.get("/ping")
    async def ping() -> JSONResponse:
        return JSONResponse({"pong": True})

    @_app.post("/mutate")
    async def mutate() -> JSONResponse:
        return JSONResponse({"ok": True})

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_mutation_without_browser_headers_is_allowed(csrf_client):
    r = await csrf_client.post("/mutate")
    assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["same-origin", "none"])
async def test_same_origin_mutation_is_allowed(csrf_client, site):
    r = await csrf_client.post("/mutate", headers={"sec-fetch-site": site})
    assert r.status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("site", ["cross-site", "same-site"])
async def test_cross_site_mutation_is_rejected(csrf_client, site):
    r = await csrf_client.post("/mutate", headers={"sec-fetch-site": site})
    assert r.status_code == 403
    assert r.json() == {"detail": "Cross-site request rejected"}


@pytest.mark.asyncio
async def test_cross_site_read_is_allowed(csrf_client):
    r = await csrf_client.get("/ping", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_origin_fallback_matching_host_is_allowed(csrf_client):
    r = await csrf_client.post("/mutate", headers={"origin": "http://test"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_origin_fallback_mismatch_is_rejected(csrf_client):
    r = await csrf_client.post("/mutate", headers={"origin": "https://evil.example"})
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_sec_fetch_site_wins_over_origin(csrf_client):
    r = await csrf_client.post(
        "/mutate",
        headers={"sec-fetch-site": "cross-site", "origin": "http://test"},
    )
    assert r.status_code == 403
