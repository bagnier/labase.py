import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from slowapi.errors import RateLimitExceeded

from app.shared.http.limiter import limiter, rate_limit


@pytest_asyncio.fixture()
async def rate_limited_client():
    _app = FastAPI()
    _app.state.limiter = limiter

    @_app.exception_handler(RateLimitExceeded)
    async def _handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    @_app.get("/ping")
    @limiter.limit("2/minute")
    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"pong": True})

    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_under_threshold(rate_limited_client):
    for _ in range(2):
        r = await rate_limited_client.get("/ping")
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_blocks_excess_requests(rate_limited_client):
    for _ in range(2):
        await rate_limited_client.get("/ping")
    r = await rate_limited_client.get("/ping")
    assert r.status_code == 429
    assert r.json() == {"detail": "Too many requests"}


def test_rate_limit_is_noop_when_disabled(monkeypatch):
    from app.shared.config import get_technical_settings

    original = get_technical_settings()
    monkeypatch.setattr(original, "rate_limit_enabled", False)

    def dummy():
        pass

    decorated = rate_limit("1/minute")(dummy)
    assert decorated is dummy
