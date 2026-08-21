"""Response helpers that absorb the JSON / HTMX-fragment / full-page branching.

One handler serves all three audiences (README: every business endpoint has two faces);
these centralize the negotiation so routers stay free of it.
"""

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from apps.shared.http.content_type import is_htmx, wants_json
from apps.shared.http.templates import templates

# What a negotiating handler answers, said where the schema can read it.
#
# `response_class=` cannot say this. FastAPI reads exactly one media type off it
# (`current_response_class.media_type`, openapi/utils.py) and that single type becomes the
# success response's whole content — `application/json` by default, `text/html` under
# `response_class=HTMLResponse`. A handler that answers both therefore describes one of them,
# whichever it happened to name. Its other job is a runtime one: it wraps a handler that
# returns a bare value, and is never used by a handler returning its own Response.
#
# `responses=` is the documentation lever, merged over whatever the response class produced —
# so naming both media types here is right whichever one the route already declared.
#
# Two types, three audiences: a fragment and a full page are both `text/html`, and which one
# a request gets is `is_htmx`, not a media type. The schema has nothing finer to say.
# It matters beyond the docs page: `client/` is generated from this schema, so a face the
# schema omits is a face no external caller can reach.
JSON_AND_HTML: dict[int | str, dict[str, Any]] = {
    200: {"content": {"application/json": {}, "text/html": {}}}
}


def or_404[T](entity: T | None) -> T:
    if entity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return entity


def mutation_response(
    request: Request,
    *,
    obj: BaseModel,
    redirect_url: str,
    htmx_redirect_url: str | None = None,
    status_code: int = 200,
) -> Response:
    """JSON clients get `obj`. Plain HTML gets a 303 redirect. HTMX gets 204 + HX-Redirect
    when htmx_redirect_url is given (a navigating mutation); callers with an in-place HTMX
    fragment update should not use this helper at all."""
    if wants_json(request):
        return JSONResponse(obj.model_dump(mode="json"), status_code=status_code)
    if htmx_redirect_url and is_htmx(request):
        r = Response(status_code=status.HTTP_204_NO_CONTENT)
        r.headers["HX-Redirect"] = htmx_redirect_url
        return r
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


def delete_response(request: Request, *, htmx_redirect_url: str | None = None) -> Response:
    """204 for JSON, always. 204 + HX-Redirect for HTMX when htmx_redirect_url is given
    (navigating away from the deleted item). Callers that re-render in place (a list
    fragment, an OOB swap) should branch on wants_json() themselves and call this only
    for the JSON case, keeping their own HTML path untouched."""
    r = Response(status_code=status.HTTP_204_NO_CONTENT)
    if htmx_redirect_url and not wants_json(request) and is_htmx(request):
        r.headers["HX-Redirect"] = htmx_redirect_url
    return r


def render_list(
    request: Request,
    *,
    fragment: str,
    full: str,
    items_key: str,
    schema: type[BaseModel],
    items: list[Any],
    user: Any,
    org: Any = None,
    context: dict | None = None,
    extra: dict | None = None,
) -> Response:
    if wants_json(request):
        return JSONResponse([schema.model_validate(i).model_dump(mode="json") for i in items])
    htmx = is_htmx(request)
    template = fragment if htmx else full
    org_handle = request.path_params.get("org_handle", "")
    ctx = {"user": user, items_key: items, "org_handle": org_handle, "org": org}
    if extra:
        ctx |= extra
    if not htmx and context:
        ctx |= context
    return templates.TemplateResponse(request, template, ctx)
