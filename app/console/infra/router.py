from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.shared.dependencies import CurrentUser
from app.shared.http.templates import templates

router = APIRouter(tags=["console"])


@router.get("", response_class=HTMLResponse)
async def console_index(request: Request, current_user: CurrentUser) -> HTMLResponse:
    return templates.TemplateResponse(request, "console.html", {"user": current_user})
