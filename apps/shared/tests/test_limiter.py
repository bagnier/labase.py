import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import ASGITransport, AsyncClient
from structlog.testing import capture_logs

from apps.shared.config import get_technical_settings
from apps.shared.http.limiter import RateLimitExceeded, UnlimitedEndpoint, rate_limit
from apps.shared.logs import capture
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


@pytest.fixture
def rate_limiting_enabled(monkeypatch):
    monkeypatch.setattr(get_technical_settings(), "rate_limit_enabled", True)


def _app(limit_string: str) -> FastAPI:
    _app = FastAPI()

    @_app.exception_handler(RateLimitExceeded)
    async def _handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({"detail": "Too many requests"}, status_code=429)

    async def ping(request: Request) -> JSONResponse:
        return JSONResponse({"pong": True})

    # A unique counter key per test run: the Postgres store outlives the test, and the bucket key
    # is module-qualified (`__qualname__`), so that is what has to be made unique.
    ping.__qualname__ = f"ping_{uuid.uuid4().hex}"
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
async def test_a_store_the_limiter_cannot_reach_is_a_bug(rate_limiting_enabled):
    """Failing open is the doctrine; failing open *quietly* is how the limiter stays off for good.
    A store that never answered is a broken dependency, and the verdict says that is an issue —
    logged at ``warning``, it rolled out of the log window and nobody ever learned the server had
    been unlimited since Tuesday. One issue, not one per request: same type, same frames."""
    capture._QUEUE.clear()
    async with AsyncClient(
        transport=ASGITransport(app=_app("1/minute")), base_url="http://test"
    ) as client:
        with patch(
            "apps.shared.http.limiter.admin_session_factory",
            side_effect=RuntimeError("db down"),
        ):
            assert (await client.get("/ping")).status_code == 200  # still fails open

    assert [type(captured.exc) for captured in capture._QUEUE] == [RuntimeError]


class _Answered(Exception):
    """A dependency that answered — the shape ``refused_status`` reads a status off."""

    def __init__(self, status: int) -> None:
        super().__init__(f"the store answered {status}")
        self.status = status


@pytest.mark.asyncio
async def test_a_store_that_answers_no_is_not_a_bug(rate_limiting_enabled):
    """The other half of the verdict: a dependency that *answered* said no, and saying no is an
    ordinary outcome — never an issue, whatever the limiter then does about it."""
    capture._QUEUE.clear()
    refused = _Answered(429)
    async with AsyncClient(
        transport=ASGITransport(app=_app("1/minute")), base_url="http://test"
    ) as client:
        with patch("apps.shared.http.limiter.admin_session_factory", side_effect=refused):
            assert (await client.get("/ping")).status_code == 200

    assert list(capture._QUEUE) == []


@pytest.mark.asyncio
async def test_rate_limit_is_noop_when_disabled():
    with patch("apps.shared.http.limiter._increment", new_callable=AsyncMock) as increment:
        async with AsyncClient(
            transport=ASGITransport(app=_app("1/minute")), base_url="http://test"
        ) as client:
            for _ in range(3):
                assert (await client.get("/ping")).status_code == 200
    increment.assert_not_awaited()


@pytest.mark.asyncio
async def test_distinct_endpoints_do_not_share_a_bucket(rate_limiting_enabled):
    """Two identically-limited endpoints must count independently (no `func.__name__` collision)."""
    keys: list[str] = []

    async def _capture(key, window_seconds):  # record the bucket key each endpoint increments
        keys.append(key)
        return 1

    app = FastAPI()

    async def alpha(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    async def beta(request: Request) -> JSONResponse:
        return JSONResponse({"ok": True})

    alpha.__qualname__ = f"alpha_{uuid.uuid4().hex}"
    beta.__qualname__ = f"beta_{uuid.uuid4().hex}"
    app.get("/a")(rate_limit("5/minute")(alpha))
    app.get("/b")(rate_limit("5/minute")(beta))

    with patch("apps.shared.http.limiter._increment", side_effect=_capture):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            await c.get("/a")
            await c.get("/b")

    assert len(keys) == 2
    assert keys[0].rsplit(":", 1)[0] != keys[1].rsplit(":", 1)[0]


@pytest.mark.asyncio
async def test_missing_request_param_fails_open_but_opens_an_issue(rate_limiting_enabled):
    """A handler without a `request` param can't be limited — it must not silently pass.

    "Loudly" used to mean ``log.error`` with no exception, which is the one level the capture
    seam ignores: the line went to the sink, rolled out of its window two days later, and an
    endpoint stayed unlimited with nothing on the issues screen ever saying so. The seam reads
    "error carrying a live exception", so the wiring bug raises one to be seen.
    """

    async def no_request() -> str:
        return "ok"

    no_request.__qualname__ = f"no_request_{uuid.uuid4().hex}"
    wrapped = rate_limit("1/minute")(no_request)

    with (
        patch("apps.shared.http.limiter._increment", new_callable=AsyncMock) as increment,
        capture_logs() as logs,
    ):
        assert await wrapped() == "ok"

    increment.assert_not_awaited()
    assert [(e["event"], e["log_level"], type(e.get("exc_info"))) for e in logs] == [
        ("rate_limit.no_request", "error", UnlimitedEndpoint)
    ]
