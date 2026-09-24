"""Content negotiation: which face a request gets — JSON, an HTMX fragment, or a full page."""

from fastapi import Request

from apps.shared.http.content_type import wants_full_page


def _mock_request(headers: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/test",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


def test_wants_full_page_true_on_htmx_history_restore():
    req = _mock_request(headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert wants_full_page(req) is True
