import json

import pytest
import structlog
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from apps.shared.http.exceptions import handle_http_error, handle_rate_limit, handle_unhandled_error
from apps.shared.http.limiter import RateLimitExceeded
from apps.shared.logs import capture


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


@pytest.mark.asyncio
async def test_handle_rate_limit_with_retry_after():
    exc = RateLimitExceeded(retry_after=60)
    req = _mock_request()
    resp = await handle_rate_limit(req, exc)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_handle_rate_limit_defaults_retry_after():
    exc = Exception("bare")
    req = _mock_request()
    resp = await handle_rate_limit(req, exc)
    assert resp.status_code == 429
    assert resp.headers["Retry-After"] == "60"


@pytest.mark.asyncio
async def test_handle_unhandled_error_html():
    req = _mock_request()
    resp = await handle_unhandled_error(req, RuntimeError("boom"))
    assert resp.status_code == 500
    assert b"Something went wrong" in bytes(resp.body)


@pytest.mark.asyncio
async def test_handle_unhandled_error_json():
    req = _mock_request(headers={"Accept": "application/json"})
    resp = await handle_unhandled_error(req, RuntimeError("boom"))
    assert resp.status_code == 500
    body = json.loads(bytes(resp.body))
    assert body == {"detail": "Internal server error"}


@pytest.mark.asyncio
async def test_handle_http_error_401_htmx():
    req = _mock_request(headers={"HX-Request": "true"})
    exc = HTTPException(status_code=401)
    resp = await handle_http_error(req, exc)
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/auth/login"


@pytest.mark.asyncio
async def test_handle_http_error_401_html_accept():
    req = _mock_request(headers={"Accept": "text/html,application/xhtml+xml"})
    exc = HTTPException(status_code=401)
    resp = await handle_http_error(req, exc)
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login?next=/test"


@pytest.mark.asyncio
async def test_handle_http_error_401_no_accept_redirects():
    req = _mock_request()
    exc = HTTPException(status_code=401)
    resp = await handle_http_error(req, exc)
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login?next=/test"


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


@pytest.mark.asyncio
async def test_the_error_page_captures_the_exception_it_was_handed(log_chain):
    """The capture seam must not depend on the frame the handler runs under: called anywhere
    ``sys.exc_info()`` is empty, a 500 that resolved the exception implicitly would open no
    issue at all — and the handler is holding the exception the whole time."""
    capture._QUEUE.clear()
    boom = RuntimeError("the request blew up")

    await handle_unhandled_error(_mock_request(), boom)

    assert [captured.exc for captured in capture._QUEUE] == [boom]


@pytest.mark.asyncio
async def test_the_error_page_carries_the_request_id(log_chain):
    """A 500 is built above the middleware that stamps every other response, so it used to be the
    one page without the id — the page a user is looking at when an admin needs to find the trace.
    """
    with structlog.contextvars.bound_contextvars(request_id="the-request"):
        resp = await handle_unhandled_error(_mock_request(), RuntimeError("boom"))

    assert resp.headers["X-Request-ID"] == "the-request"
