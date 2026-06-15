import json

import pytest
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from app.shared.http.exceptions import handle_http_error, handle_rate_limit, handle_unhandled_error


def _mock_request(headers: dict | None = None, scope_extras: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        **(scope_extras or {}),
    }
    return Request(scope)


class _FakeGranularity:
    def __init__(self, seconds):
        self.seconds = seconds


class _FakeItem:
    def __init__(self, seconds, multiples=None):
        self.GRANULARITY = _FakeGranularity(seconds)
        self.multiples = multiples


class _FakeLimit:
    def __init__(self, item):
        self.limit = item


class _FakeRateLimitExc(Exception):
    def __init__(self, item=None):
        self.limit = _FakeLimit(item) if item is not None else None


@pytest.mark.asyncio
async def test_handle_rate_limit_with_retry_after():
    exc = _FakeRateLimitExc(_FakeItem(seconds=60, multiples=1))
    req = _mock_request()
    resp = await handle_rate_limit(req, exc)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_handle_rate_limit_multiples():
    exc = _FakeRateLimitExc(_FakeItem(seconds=60, multiples=2))
    req = _mock_request()
    resp = await handle_rate_limit(req, exc)
    assert resp.headers["Retry-After"] == "120"


@pytest.mark.asyncio
async def test_handle_rate_limit_no_limit_attr():
    exc = Exception("bare")
    req = _mock_request()
    resp = await handle_rate_limit(req, exc)
    assert resp.status_code == 429
    assert "Retry-After" not in resp.headers


@pytest.mark.asyncio
async def test_handle_unhandled_error():
    req = _mock_request()
    resp = await handle_unhandled_error(req, RuntimeError("boom"))
    assert resp.status_code == 500
    body = json.loads(bytes(resp.body))
    assert body == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_handle_http_error_401_htmx():
    req = _mock_request(headers={"HX-Request": "true"})
    exc = HTTPException(status_code=401)
    resp = await handle_http_error(req, exc)
    assert resp.status_code == 200
    assert resp.headers["HX-Redirect"] == "/auth/login"


@pytest.mark.asyncio
async def test_handle_http_error_401_html_accept():
    req = _mock_request(headers={"Accept": "text/html,application/xhtml+xml"})
    exc = HTTPException(status_code=401)
    resp = await handle_http_error(req, exc)
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login"


@pytest.mark.asyncio
async def test_handle_http_error_403_json():
    req = _mock_request(headers={"accept": "application/json"})
    exc = HTTPException(status_code=403, detail="Forbidden")
    resp = await handle_http_error(req, exc)
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_handle_http_error_403_html():
    from fastapi.responses import HTMLResponse

    req = _mock_request()
    exc = HTTPException(status_code=403, detail="Forbidden")
    resp = await handle_http_error(req, exc)
    assert isinstance(resp, HTMLResponse)
    assert resp.status_code == 403
