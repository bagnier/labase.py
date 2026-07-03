from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from apps.shared.http.responses import delete_response, mutation_response


def _mock_request(headers: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/test",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    return Request(scope)


class _Thing(BaseModel):
    id: int
    name: str


def test_mutation_response_json_returns_object():
    req = _mock_request(headers={"Accept": "application/json"})
    resp = mutation_response(req, obj=_Thing(id=1, name="a"), redirect_url="/things")
    assert isinstance(resp, JSONResponse)
    assert resp.status_code == 200
    import json

    assert json.loads(bytes(resp.body)) == {"id": 1, "name": "a"}


def test_mutation_response_json_custom_status_code():
    req = _mock_request(headers={"Accept": "application/json"})
    resp = mutation_response(
        req, obj=_Thing(id=1, name="a"), redirect_url="/things", status_code=201
    )
    assert resp.status_code == 201


def test_mutation_response_plain_html_redirects_303():
    req = _mock_request()
    resp = mutation_response(req, obj=_Thing(id=1, name="a"), redirect_url="/things")
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/things"


def test_mutation_response_htmx_redirects_204():
    req = _mock_request(headers={"HX-Request": "true"})
    resp = mutation_response(
        req,
        obj=_Thing(id=1, name="a"),
        redirect_url="/things",
        htmx_redirect_url="/things/1",
    )
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/things/1"


def test_mutation_response_htmx_without_htmx_redirect_url_falls_back_to_303():
    req = _mock_request(headers={"HX-Request": "true"})
    resp = mutation_response(req, obj=_Thing(id=1, name="a"), redirect_url="/things")
    assert isinstance(resp, RedirectResponse)
    assert resp.status_code == 303


def test_delete_response_json_is_204():
    req = _mock_request(headers={"Accept": "application/json"})
    resp = delete_response(req)
    assert resp.status_code == 204
    assert "HX-Redirect" not in resp.headers


def test_delete_response_json_ignores_htmx_redirect_url():
    req = _mock_request(headers={"Accept": "application/json", "HX-Request": "true"})
    resp = delete_response(req, htmx_redirect_url="/things")
    assert resp.status_code == 204
    assert "HX-Redirect" not in resp.headers


def test_delete_response_htmx_redirects_204():
    req = _mock_request(headers={"HX-Request": "true"})
    resp = delete_response(req, htmx_redirect_url="/things")
    assert resp.status_code == 204
    assert resp.headers["HX-Redirect"] == "/things"


def test_delete_response_plain_html_is_204_no_redirect():
    req = _mock_request()
    resp = delete_response(req, htmx_redirect_url="/things")
    assert resp.status_code == 204
    assert "HX-Redirect" not in resp.headers
