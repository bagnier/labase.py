"""The request-logging policy: one line per request, and only when it's a failure worth an
admin's eyes — every 5xx, plus a 4xx that is a *dead link from ourselves* (same-host Referer to a
non-asset path). Successful requests, bot scans and the browser's favicon probe stay silent.

Pure middleware logic — no DB, no running app: the decision is exercised through fake requests.
"""

from starlette.requests import Request

from apps.shared.observability import request as R


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


def _decision(monkeypatch, path: str, status: int, referer: str | None) -> str:
    calls: dict[str, bool] = {}
    monkeypatch.setattr(R.log, "warning", lambda *a, **k: calls.setdefault("warning", True))
    monkeypatch.setattr(R.log, "error", lambda *a, **k: calls.setdefault("error", True))
    monkeypatch.setattr(R, "read_request_stats", lambda: None)
    R.RequestLogger._log_if_failed(_req(path, referer=referer), status, 12.3)
    return "error" if "error" in calls else "warning" if "warning" in calls else "none"


def test_is_asset_matches_favicon_static_and_extensions():
    assert R._is_asset("/favicon.ico")
    assert R._is_asset("/static/app.css")
    assert R._is_asset("/x/logo.png")
    assert not R._is_asset("/console/logs")
    assert not R._is_asset("/acme/missing")


def test_internal_referer_is_same_host_only():
    assert R._is_internal_referer(_req("/x", referer="https://example.com/page"))
    assert not R._is_internal_referer(_req("/x", referer="https://evil.com/page"))
    assert not R._is_internal_referer(_req("/x", referer=None))


def test_favicon_404_stays_silent_even_from_our_page(monkeypatch):
    assert _decision(monkeypatch, "/favicon.ico", 404, "https://example.com/home") == "none"


def test_internal_dead_link_404_logs_a_warning(monkeypatch):
    assert _decision(monkeypatch, "/acme/missing", 404, "https://example.com/acme/") == "warning"


def test_external_or_refererless_404_stays_silent(monkeypatch):
    assert _decision(monkeypatch, "/wp-login.php", 404, None) == "none"


def test_every_5xx_logs_an_error_regardless_of_referer(monkeypatch):
    assert _decision(monkeypatch, "/api/x", 500, None) == "error"
    assert _decision(monkeypatch, "/static/x.js", 503, None) == "error"


def test_successful_request_leaves_no_row(monkeypatch):
    assert _decision(monkeypatch, "/console/logs", 200, "https://example.com/") == "none"
