from fastapi import Request
from fastapi.responses import Response

from apps.shared.http import with_etag


def _request(if_none_match: str | None = None) -> Request:
    headers = [(b"if-none-match", if_none_match.encode())] if if_none_match is not None else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def test_first_request_gets_etag_and_cache_control():
    response = with_etag(_request(), Response(content=b"<html>hi</html>"))
    assert response.status_code == 200
    etag = response.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    assert response.headers["cache-control"] == "private, no-cache"


def test_matching_if_none_match_returns_304_with_empty_body():
    etag = with_etag(_request(), Response(content=b"<html>hi</html>")).headers["etag"]
    not_modified = with_etag(_request(if_none_match=etag), Response(content=b"<html>hi</html>"))
    assert not_modified.status_code == 304
    assert not_modified.body == b""
    assert not_modified.headers["etag"] == etag
    assert not_modified.headers["cache-control"] == "private, no-cache"


def test_changed_body_yields_a_different_etag():
    old = with_etag(_request(), Response(content=b"<html>v1</html>")).headers["etag"]
    fresh = with_etag(_request(if_none_match=old), Response(content=b"<html>v2</html>"))
    assert fresh.status_code == 200
    assert fresh.headers["etag"] != old


def test_wildcard_if_none_match_matches():
    not_modified = with_etag(_request(if_none_match="*"), Response(content=b"<html>hi</html>"))
    assert not_modified.status_code == 304


def test_stale_if_none_match_serves_full_response():
    fresh = with_etag(_request(if_none_match='"stale"'), Response(content=b"<html>hi</html>"))
    assert fresh.status_code == 200
    assert fresh.body == b"<html>hi</html>"
