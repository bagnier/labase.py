"""Response helpers that absorb the JSON / fragment / full-page branching
(AGENTS: one set of helpers branches JSON, fragment and page).
"""

from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel

from apps.shared.http.content_type import is_htmx, wants_full_page, wants_json
from apps.shared.http.templates import templates

# The OpenAPI side of negotiation. `response_class=` documents a single media type, so a route
# answering both JSON and HTML names them through `responses=`, merged over it. The schema
# matters beyond the docs: `client/` is generated from it. Fragment and full page are both
# `text/html`.

# FastAPI's own annotation for `responses=`; a TypedDict would not satisfy it.
type Responses = dict[int | str, dict[str, Any]]


def json_and_html(model: Any) -> Responses:
    """JSON as ``model``, plus HTML. The route must not set ``response_class=HTMLResponse``,
    which would document ``model`` as the HTML's shape."""
    return {200: {"model": model, "content": {"text/html": {}}}}


# A deletion: the route's ``status_code=204`` for JSON, a re-rendered 200 page for a browser.
HTML_AFTER_DELETE: Responses = {200: {"content": {"text/html": {}}}}


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
    """JSON gets ``obj``; HTML a 303 to ``redirect_url``; HTMX a 204 + ``HX-Redirect`` when
    ``htmx_redirect_url`` is given. Not for a mutation that swaps a fragment in place."""
    if wants_json(request):
        return JSONResponse(obj.model_dump(mode="json"), status_code=status_code)
    if htmx_redirect_url and is_htmx(request):
        r = Response(status_code=status.HTTP_204_NO_CONTENT)
        r.headers["HX-Redirect"] = htmx_redirect_url
        return r
    return RedirectResponse(redirect_url, status_code=status.HTTP_303_SEE_OTHER)


def delete_response(request: Request, *, htmx_redirect_url: str | None = None) -> Response:
    """A 204, plus ``HX-Redirect`` for HTMX when ``htmx_redirect_url`` is given. A route that
    re-renders in place calls it only for JSON."""
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
    full_page = wants_full_page(request)
    template = full if full_page else fragment
    org_handle = request.path_params.get("org_handle", "")
    ctx = {"user": user, items_key: items, "org_handle": org_handle, "org": org}
    if extra:
        ctx |= extra
    if full_page and context:
        ctx |= context
    return templates.TemplateResponse(request, template, ctx)
