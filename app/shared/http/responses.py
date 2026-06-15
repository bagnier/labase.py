from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from app.shared.http.content_type import wants_json
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
    org: Any = None,
    shell: dict | None = None,
) -> Response:
    if wants_json(request):
        return JSONResponse([schema.model_validate(i).model_dump(mode="json") for i in items])
    is_htmx = request.headers.get("HX-Request") == "true"
    template = fragment if is_htmx else full
    org_handle = request.path_params.get("org_handle", "")
    ctx = {"user": user, items_key: items, "org_handle": org_handle, "org": org}
    if not is_htmx and shell:
        ctx |= shell
    return templates.TemplateResponse(request, template, ctx)
