import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient

from apps.shared.config import get_technical_settings
from apps.shared.http.limiter import RateLimitExceeded, rate_limit
from apps.shared.persistence import database as db


@pytest_asyncio.fixture(autouse=True)
async def fresh_admin_engine():
    """The cached admin engine binds to one event loop; give each test its own."""
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()
    yield
    await db._admin_engine().dispose()
    db._admin_engine.cache_clear()
    db.admin_session_factory.cache_clear()


@pytest.fixture()
def rate_limiting_enabled(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "rate_limit_enabled", True)


def _app(limit_string: str) -> FastAPI:
    _app = FastAPI()

    @_app.exception_handler(RateLimitExceeded)
    async def _handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"pong": True})

    # unique counter key per test run: the Postgres store outlives the test
    ping.__name__ = f"ping_{uuid.uuid4().hex}"
    _app.get("/ping")(rate_limit(limit_string)(ping))
    return _app


@pytest_asyncio.fixture()
async def rate_limited_client(rate_limiting_enabled):
    async with AsyncClient(
        transport=ASGITransport(app=_app("2/minute")), base_url="http://test"
    ) as c:
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


@pytest.mark.asyncio
async def test_rate_limit_counts_per_client_in_shared_store(rate_limiting_enabled):
    """Two transports (≈ two app instances) share the same Postgres counters."""
    app = _app("2/minute")
    async with (
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as first,
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as second,
    ):
        assert (await first.get("/ping")).status_code == 200
        assert (await second.get("/ping")).status_code == 200
        assert (await second.get("/ping")).status_code == 429


@pytest.mark.asyncio
async def test_rate_limit_fails_open_when_store_is_down(rate_limiting_enabled):
    async with AsyncClient(
        transport=ASGITransport(app=_app("1/minute")), base_url="http://test"
    ) as client:
        with patch(
            "apps.shared.http.limiter.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ):
            for _ in range(3):
                assert (await client.get("/ping")).status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_is_noop_when_disabled():
    with patch("apps.shared.http.limiter._increment", new_callable=AsyncMock) as increment:
        async with AsyncClient(
            transport=ASGITransport(app=_app("1/minute")), base_url="http://test"
        ) as client:
            for _ in range(3):
                assert (await client.get("/ping")).status_code == 200
    increment.assert_not_awaited()
