"""The request-logging policy: one line per request, and only when it's a failure worth an
admin's eyes — every 5xx, plus a 4xx that is a *dead link from ourselves* (same-host Referer to a
non-asset path). Successful requests, bot scans and the browser's favicon probe stay silent.

Pure middleware logic — no DB, no running app: the decision is exercised through fake requests.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request

from apps.shared.http.exceptions import handle_http_error, handle_stale_data
from apps.shared.logs import request
from apps.shared.metrics import accumulator


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
    """The levels of the lines a served exchange leaves behind — driven through the real
    middleware and read back out of the real log sink, so the policy is observed, not mocked."""
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
# A refusal used to leave two lines: ``request.rejected`` from the exception handler and
# ``request.finished`` from the middleware, both about the same exchange — and the noisier of the
# two also traced the asset 404s the quieter one deliberately skips. ``detail`` was the only thing
# the second line held that the first did not, so it moved onto the first, and the level moved with
# it: what the code could not carry through and answered with a 4xx is a warning.
#
# A 404 is the exception to that: "there is nothing here" is not a refusal, and a stray URL is not
# ours to fix — so it stays at ``info`` unless it is a dead link from one of our own pages.


def _refused(log_chain, path: str, raiser, *, referer: str | None = None):
    """Serve one exchange whose handler raises, through the *real* exception handlers."""
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
    """Two lines said the same exchange twice; the second only ever added its ``detail``."""
    lines = _refused(log_chain, "/acme/settings", _raise_http(403, "Owners only"))

    assert lines == [("request.finished", "warning", "Owners only")]


def test_a_stray_url_is_not_something_we_refused(log_chain):
    """A 404 nobody linked to is a scan, not a failure of ours — the level says so."""
    lines = _refused(log_chain, "/wp-login.php", _raise_http(404, "Not Found"))

    assert lines == [("request.finished", "info", "Not Found")]


def test_an_asset_the_browser_fetched_itself_still_leaves_nothing_when_refused(log_chain):
    """What the rejected line used to trace and the finished line never did: a row per missing
    image would bury the traffic it sits between."""
    lines = _refused(log_chain, "/static/gone.css", _raise_http(404, "Not Found"))

    assert lines == []


def test_a_conflict_leaves_one_line_too(log_chain):
    """``request.conflict`` was the same double, on the 409 an optimistic lock answers with."""

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
    """A scan is a served exchange like any other — the level says it was nothing to fix.
    It stays out of the load metrics, which is where flooding would actually hurt."""
    assert _levels_for(log_chain, "/wp-login.php", 404) == ["info"]


def test_a_5xx_is_traced_at_error(log_chain):
    assert _levels_for(log_chain, "/api/x", 500) == ["error"]


def test_a_5xx_on_an_asset_is_traced_too(log_chain):
    """The only thing that brings an asset back into the timeline: a 5xx is ours to fix,
    whoever asked for the file."""
    assert _levels_for(log_chain, "/static/x.js", 503) == ["error"]


def test_an_asset_the_browser_fetched_itself_leaves_no_line(log_chain):
    assert _levels_for(log_chain, "/favicon.ico", 404, "https://example.com/home") == []


# The load metrics count the same universe the timeline shows: our own traffic and our own
# failures, never the bot-scan / favicon noise that would otherwise flood ``GET unmatched``.


def test_load_metrics_count_success_and_server_errors():
    assert request._feeds_load_metrics(_req("/todo"), 200)
    assert request._feeds_load_metrics(_req("/todo"), 302)
    assert request._feeds_load_metrics(_req("/api/x"), 500)


def test_load_metrics_drop_bot_and_favicon_4xx():
    assert not request._feeds_load_metrics(_req("/wp-login.php"), 404)  # no referer — a scan
    assert not request._feeds_load_metrics(_req("/x", referer="https://evil.com/"), 404)  # external
    favicon = _req("/favicon.ico", referer="https://example.com/")
    assert not request._feeds_load_metrics(favicon, 404)


def test_load_metrics_count_internal_dead_links():
    dead_link = _req("/acme/missing", referer="https://example.com/acme/")
    assert request._feeds_load_metrics(dead_link, 404)


# ``/.well-known/*`` is fetched by the browser/infra itself (Chrome's devtools probe), so even
# with a same-host referer it is noise, not a dead link — dropped from both logs and metrics.


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
    """The correlation key is stored whole; only the screen shortens it.

    Truncated to 8 hex chars at the source it would be 32 bits — a birthday collision around 77k
    requests, merging two unrelated requests under one filter in the Logs viewer. The journal keeps
    the full uuid (its column is typed for it) and `_short` shortens it for display, which is where
    a shortened id is actually useful.
    """
    rid = request.new_request_id()
    assert uuid.UUID(rid)  # parses whole — not a prefix
    assert len(rid) == 36


# The metrics label is the *matched template*, prefix included — `/console/admins/{email}`, never
# the router-relative `/admins/{email}`. Since FastAPI 0.137 `include_router` keeps the child
# router instead of cloning its routes under the prefix, so `scope["route"].path` is the path as
# the child declared it; the full template lives on the effective route context.


def _label_for(path: str) -> str:
    app = FastAPI()
    router = APIRouter()
    # `lambda: {}` and not `dict` (what PIE807 proposes): FastAPI introspects the endpoint
    # signature, and `inspect.signature` has none to give for a builtin type.
    router.get("")(lambda: {})
    router.get("/admins/{email}")(lambda email: {})
    app.include_router(router, prefix="/console")
    app.add_middleware(request.RequestLogger)
    accumulator.reset()

    TestClient(app).get(path)

    return next(route for _method, route in accumulator.snapshot())


def test_the_metric_label_carries_the_router_prefix():
    assert _label_for("/console/admins/a@b.example") == "/console/admins/{email}"


def test_the_metric_label_of_a_prefix_only_route_is_the_prefix():
    assert _label_for("/console") == "/console"


# One line per served request, under one name: ``request.finished``, whose *level* carries the
# outcome. That is the name the timeline feature, its mockup and both e2e drivers already read.


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
    """The 5xx an admin most wants to find is the one nobody handled. The exception travels back
    *through* this middleware, so the line has to be written on the way out and the exception
    re-raised — Starlette's own 500 handler is what turns it into an issue, one layer further up.
    """
    TestClient(_serving_app(), raise_server_exceptions=False).get("/boom")

    lines = log_chain()

    assert [(line.name, line.level, line.payload["status"]) for line in lines] == [
        ("request.finished", "error", 500)
    ]


# The four correlation keys are the timeline's whole point, and three of them are bound *below*
# this middleware — by auth's ``get_current_user`` and organizations' ``get_current_org``, as the
# request is served. The finished line is written after that, so it must see them.


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
