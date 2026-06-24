from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from apps.pages.infra.repository import PageNavRepository, org_by_handle, visible_pages
from apps.public.contract import settings
from apps.shared.http.templates import templates
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, admin: AdminSession) -> HTMLResponse:
    handle: str = settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        return templates.TemplateResponse(request, "home.html")
    org = await org_by_handle(admin, handle)
    if org is None:
        return templates.TemplateResponse(request, "home.html")
    pages = await visible_pages(admin, org.id, role=None)
    nav_items = await PageNavRepository(admin, org.id).nav_items(public_only=True)
    return templates.TemplateResponse(
        request,
        "home_featured.html",
        {"org": org, "org_handle": handle, "pages": pages, "page_nav": nav_items},
    )
