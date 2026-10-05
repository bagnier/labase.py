"""``RequestLogger``: which exchanges leave a ``request.finished`` line, at which level, and what
reaches the load metrics. No database."""

import asyncio
import uuid
from collections import deque

import pytest
import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.types import Message, Receive, Scope, Send

from apps.shared.http.exceptions import handle_http_error, handle_stale_data
from apps.shared.logs import capture, request, sink
from apps.shared.logs.capture import ExceptionCaptured


def _req(path: str, *, referer: str | None = None, host: str = "example.com") -> Request:
    headers = [(b"referer", referer.encode())] if referer else []
    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": headers,
        "server": (host, 443),
        "scheme": "https",
        "query_string": b"",
    }
    return Request(scope)


def _levels_for(log_chain, path: str, status: int, referer: str | None = None) -> list[str]:
    """The levels of the lines one exchange leaves, through the real middleware and sink."""
    app = FastAPI()
    app.get("/{whole_path:path}")(lambda: Response(status_code=status))
    app.add_middleware(request.RequestLogger)
    headers = {"referer": referer} if referer else {}
    TestClient(app, base_url="https://example.com").get(path, headers=headers)
    return [line.level for line in log_chain()]


def test_is_asset_matches_favicon_static_and_extensions():
    assert request._is_asset("/favicon.ico")
    assert request._is_asset("/static/app.css")
    assert request._is_asset("/x/logo.png")
    assert not request._is_asset("/console/timeline")
    assert not request._is_asset("/acme/missing")


def test_internal_referer_is_same_host_only():
    assert request._is_internal_referer(_req("/x", referer="https://example.com/page"))
    assert not request._is_internal_referer(_req("/x", referer="https://evil.com/page"))
    assert not request._is_internal_referer(_req("/x", referer=None))


# ── One line, whatever refused the exchange ──────────────────────────────────────────────────
#
# A refusal is one ``request.finished`` warning carrying its ``detail``. A 404 stays ``info``
# unless it is a dead link from one of our pages.


def _refused(log_chain, path: str, raiser, *, referer: str | None = None):
    """Serve one exchange whose handler raises, through the real exception handlers."""
    app = FastAPI()
    app.get("/{whole_path:path}")(raiser)
    app.exception_handler(HTTPException)(handle_http_error)
    app.exception_handler(StarletteHTTPException)(handle_http_error)
    app.exception_handler(StaleDataError)(handle_stale_data)
    app.add_middleware(request.RequestLogger)
    headers = {"referer": referer} if referer else {}
    TestClient(app, base_url="https://example.com").get(path, headers=headers)
    return [(line.name, line.level, line.payload.get("detail")) for line in log_chain()]


def _raise_http(status: int, detail: str):
    def handler():
        raise HTTPException(status_code=status, detail=detail)

    return handler


def test_a_refusal_leaves_one_line_carrying_what_it_refused(log_chain):
    lines = _refused(log_chain, "/acme/settings", _raise_http(403, "Owners only"))

    assert lines == [("request.finished", "warning", "Owners only")]


def test_a_stray_url_is_not_something_we_refused(log_chain):
    lines = _refused(log_chain, "/wp-login.php", _raise_http(404, "Not Found"))

    assert lines == [("request.finished", "info", "Not Found")]


def test_an_asset_the_browser_fetched_itself_still_leaves_nothing_when_refused(log_chain):
    lines = _refused(log_chain, "/static/gone.css", _raise_http(404, "Not Found"))

    assert lines == []


def test_a_conflict_leaves_one_line_too(log_chain):

    def stale():
        raise StaleDataError("row changed under us")

    lines = _refused(log_chain, "/acme/todos/1", stale)

    assert lines == [
        ("request.finished", "warning", "This was changed by someone else. Please retry.")
    ]


def test_a_successful_request_is_traced_at_info(log_chain):
    assert _levels_for(log_chain, "/console/timeline", 200, "https://example.com/") == ["info"]


def test_an_internal_dead_link_404_is_traced_at_warning(log_chain):
    assert _levels_for(log_chain, "/acme/missing", 404, "https://example.com/acme/") == ["warning"]


def test_a_bot_scan_404_is_still_traffic_and_traced_at_info(log_chain):
    assert _levels_for(log_chain, "/wp-login.php", 404) == ["info"]


def test_a_5xx_is_traced_at_error(log_chain):
    assert _levels_for(log_chain, "/api/x", 500) == ["error"]


def test_a_5xx_on_an_asset_is_traced_too(log_chain):
    assert _levels_for(log_chain, "/static/x.js", 503) == ["error"]


def test_an_asset_the_browser_fetched_itself_leaves_no_line(log_chain):
    assert _levels_for(log_chain, "/favicon.ico", 404, "https://example.com/home") == []


# A health probe is silent while healthy and traced when it fails. These four hold the probe half
# of the claim "health-probe-exemption" (tests/meta/claims.py).


def test_a_healthy_readiness_probe_leaves_no_line(log_chain):
    assert _levels_for(log_chain, "/health/ready", 200) == []


def test_a_healthy_liveness_probe_leaves_no_line(log_chain):
    assert _levels_for(log_chain, "/health/live", 200) == []


def test_a_failing_readiness_probe_is_traced_at_error(log_chain):
    assert _levels_for(log_chain, "/health/ready", 503) == ["error"]


def test_a_failing_liveness_probe_is_traced_at_error(log_chain):
    assert _levels_for(log_chain, "/health/live", 503) == ["error"]


# The load metrics count our traffic and our failures, not scans that would flood
# ``GET unmatched``.


def test_load_metrics_count_success_and_server_errors():
    assert request._feeds_load_metrics(_req("/todo"), 200)
    assert request._feeds_load_metrics(_req("/todo"), 302)
    assert request._feeds_load_metrics(_req("/api/x"), 500)


def test_load_metrics_drop_bot_and_favicon_4xx():
    assert not request._feeds_load_metrics(_req("/wp-login.php"), 404)
    assert not request._feeds_load_metrics(_req("/x", referer="https://evil.com/"), 404)
    favicon = _req("/favicon.ico", referer="https://example.com/")
    assert not request._feeds_load_metrics(favicon, 404)


def test_load_metrics_count_internal_dead_links():
    dead_link = _req("/acme/missing", referer="https://example.com/acme/")
    assert request._feeds_load_metrics(dead_link, 404)


# ``/.well-known/*`` is fetched by the browser itself: never a dead link, even from our page.


def test_well_known_probe_is_an_infra_probe():
    assert request._is_infra_probe("/.well-known/appspecific/com.chrome.devtools.json")
    assert not request._is_infra_probe("/acme/missing")


def test_well_known_probe_stays_silent_even_from_our_page(log_chain):
    path = "/.well-known/appspecific/com.chrome.devtools.json"
    assert _levels_for(log_chain, path, 404, "https://example.com/home") == []


def test_well_known_probe_stays_out_of_the_load_metrics():
    path = "/.well-known/appspecific/com.chrome.devtools.json"
    assert not request._feeds_load_metrics(_req(path, referer="https://example.com/home"), 404)


def test_the_request_id_is_a_whole_uuid_not_a_prefix():
    """8 hex chars would collide around 77k requests; only the display shortens it."""
    rid = request.new_request_id()
    assert uuid.UUID(rid)
    assert len(rid) == 36


# The exchange is offered to registered observers (``apps/metrics``), which shared cannot name.


@pytest.fixture
def measured(monkeypatch):
    """What the middleware handed its observers. Through ``monkeypatch``, so ``apps/metrics``'s
    real subscription comes back at teardown."""
    calls: list[tuple] = []

    def _record(method, label, status_code, duration_ms, *, unmatched=False):
        calls.append((method, label, status_code, duration_ms, unmatched))

    monkeypatch.setattr(request, "_observers", [_record])
    return calls


def _serve(path: str, *, status: int = 200, referer: str | None = None) -> None:
    """One exchange through the real middleware, on a router under a prefix.

    ``lambda: {}``, not ``dict`` (PIE807): FastAPI cannot read a builtin's signature.
    """
    app = FastAPI()
    router = APIRouter()
    router.get("")(lambda: {})
    router.get("/admins/{email}")(lambda email: Response(status_code=status))
    app.include_router(router, prefix="/console")
    app.add_middleware(request.RequestLogger)
    TestClient(app).get(path, headers={"referer": referer} if referer else {})


def test_a_served_request_reaches_the_observer_under_its_route_template(measured):
    _serve("/console/admins/a@b.example")
    assert [(m, label, s, u) for m, label, s, _ms, u in measured] == [
        ("GET", "/console/admins/{email}", 200, False)
    ]


def test_an_exchange_is_served_when_nothing_is_measuring_it(log_chain, monkeypatch):
    """With the metrics app off or deleted, nobody registers and the request does not notice."""
    monkeypatch.setattr(request, "_observers", [])
    app = FastAPI()
    app.get("/console/admins/{email}")(lambda email: Response(status_code=200))
    app.add_middleware(request.RequestLogger)
    response = TestClient(app).get("/console/admins/a@b.example")
    lines = [(line.name, line.level) for line in log_chain()]
    assert (response.status_code, lines) == (200, [("request.finished", "info")])


def test_a_dead_link_of_ours_reaches_the_observer_as_an_unmatched_real_path(measured):
    _serve("/console/gone", referer="http://testserver/console")
    assert [(m, label, s, u) for m, label, s, _ms, u in measured] == [
        ("GET", "/console/gone", 404, True)
    ]


# The label is the full template, prefix included (see ``request._route_template``).


def test_the_metric_label_carries_the_router_prefix(measured):
    _serve("/console/admins/a@b.example")
    assert [label for _m, label, *_rest in measured] == ["/console/admins/{email}"]


def test_the_metric_label_of_a_prefix_only_route_is_the_prefix(measured):
    _serve("/console")
    assert [label for _m, label, *_rest in measured] == ["/console"]


def test_an_observer_that_raises_is_isolated_from_the_others(measured):

    def boom(*args, **kwargs):
        raise RuntimeError("observer broke")

    request._observers.insert(0, boom)

    _serve("/console/admins/a@b.example")

    assert [(m, label, s, u) for m, label, s, _ms, u in measured] == [
        ("GET", "/console/admins/{email}", 200, False)
    ]


# One ``request.finished`` line per served request, its level carrying the outcome.


def _explode() -> None:
    raise RuntimeError("the handler gave up")


def _serving_app() -> FastAPI:
    app = FastAPI()
    app.get("/console/timeline")(lambda: {"ok": True})
    app.get("/boom")(_explode)
    app.add_middleware(request.RequestLogger)
    return app


def test_a_served_request_leaves_one_finished_line(log_chain):
    TestClient(_serving_app()).get("/console/timeline")
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("request.finished", "info")]


def test_a_handler_that_raises_still_leaves_its_finished_line(log_chain):
    """The line is written on the exception's way out; Starlette's 500 handler, above, opens
    the issue."""
    TestClient(_serving_app(), raise_server_exceptions=False).get("/boom")

    lines = log_chain()

    assert [(line.name, line.level, line.payload["status"]) for line in lines] == [
        ("request.finished", "error", 500)
    ]


async def _cancelling_app(scope: Scope, receive: Receive, send: Send) -> None:
    raise asyncio.CancelledError()


async def _no_messages() -> Message:
    return {"type": "http.disconnect"}


async def _discard(message: Message) -> None:
    pass


def test_a_client_disconnect_still_leaves_its_finished_line(log_chain):
    """``CancelledError`` is a ``BaseException``: the line is still written, and the cancellation
    goes on."""
    middleware = request.RequestLogger(_cancelling_app)
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/boom",
        "headers": [],
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
        "client": None,
    }

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(middleware(scope, _no_messages, _discard))

    lines = log_chain()
    assert [(line.name, line.level, line.payload["status"]) for line in lines] == [
        ("request.finished", "error", 500)
    ]


def test_a_raising_observer_never_replaces_the_handlers_own_exception(log_chain, monkeypatch):
    """Else the observer's failure would be captured instead of the 500, and the line lost."""

    def _boom_observer(*args, **kwargs):
        raise RuntimeError("observer broke")

    monkeypatch.setattr(request, "_observers", [_boom_observer])

    with pytest.raises(RuntimeError, match="the handler gave up"):
        TestClient(_serving_app()).get("/boom")

    lines = log_chain()

    assert [(line.name, line.level) for line in lines] == [
        ("request.finished", "error"),
        ("request.observer_failed", "error"),
    ]
    assert next(line for line in lines if line.name == "request.finished").payload["status"] == 500


# ``user_id`` and ``org_id`` are bound below this middleware, by auth and organizations.


def _correlated_app() -> FastAPI:
    async def bind_the_scope() -> None:
        structlog.contextvars.bind_contextvars(user_id="u-1", org_id="o-1")

    app = FastAPI()
    app.get("/acme/todo", dependencies=[Depends(bind_the_scope)])(lambda: {"ok": True})
    app.add_middleware(request.RequestLogger)
    return app


def test_the_finished_line_carries_what_the_request_bound_below_it(log_chain):
    TestClient(_correlated_app()).get("/acme/todo")

    lines = log_chain()

    assert [(line.name, line.user_id, line.org_id) for line in lines] == [
        ("request.finished", "u-1", "o-1")
    ]


# Full log and capture queues never block, slow or fail the request.


def _logging_app() -> FastAPI:
    log = structlog.get_logger("apps.todo.probe")

    async def logs_and_answers() -> dict[str, bool]:
        try:
            raise ValueError("observed, not suffered")
        except ValueError:
            log.exception("todo.probe_failed")
        return {"ok": True}

    app = FastAPI()
    app.get("/probe")(logs_and_answers)
    app.add_middleware(request.RequestLogger)
    return app


def test_a_full_sink_and_a_full_capture_queue_leave_the_request_untouched(log_chain, monkeypatch):
    """Two lines displace the sink's one slot, one capture the capture queue's; only the tallies
    move."""
    monkeypatch.setattr(sink, "_QUEUE", deque([{"event": "older"}], maxlen=1))
    monkeypatch.setattr(
        capture, "_QUEUE", deque([ExceptionCaptured(exc=RuntimeError("older"))], maxlen=1)
    )
    sink._overflow.dropped = 0
    capture._overflow.dropped = 0

    response = TestClient(_logging_app()).get("/probe")

    assert (
        response.status_code,
        response.json(),
        sink._overflow.dropped,
        capture._overflow.dropped,
    ) == (200, {"ok": True}, 2, 1)
