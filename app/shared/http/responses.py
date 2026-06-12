from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.shared.http.templates import templates


def render_list(
    request: Request,
    *,
    fragment: str,
    full: str,
    items_key: str,
    schema: type[BaseModel],
    items: list[Any],
    user: Any,
) -> Response:
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse([schema.model_validate(i).model_dump(mode="json") for i in items])
    is_htmx = request.headers.get("HX-Request") == "true"
    template = fragment if is_htmx else full
    org_slug = request.path_params.get("org_slug", "")
    ctx = {"user": user, items_key: items, "org_slug": org_slug}
    return templates.TemplateResponse(request, template, ctx)
