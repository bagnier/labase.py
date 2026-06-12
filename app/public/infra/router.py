from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.shared.http.templates import templates

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html")
