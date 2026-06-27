from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from apps.shared.http.templates import templates

router = APIRouter(prefix="/styleguide", tags=["styleguide"])


@router.get("", response_class=HTMLResponse)
async def styleguide(request: Request) -> HTMLResponse:
    """Living demo of the DaisyUI component library used across the app."""
    return templates.TemplateResponse(request, "styleguide/index.html", {})
