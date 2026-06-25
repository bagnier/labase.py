from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from apps.auth.contract.current import OptionalCurrentUser
from apps.pages.domain.models import PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import (
    PageNavRepository,
    PageRepository,
    org_by_handle,
    visible_pages,
)
from apps.public.contract import settings
from apps.shared.http.templates import templates
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse, response_model=None)
async def index(
    request: Request, admin: AdminSession, current_user: OptionalCurrentUser
) -> HTMLResponse | RedirectResponse:
    handle: str = settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        return templates.TemplateResponse(request, "home.html")
    org = await org_by_handle(admin, handle)
    if org is None:
        return templates.TemplateResponse(request, "home.html")
    nav_items = await PageNavRepository(admin, org.id).nav_items(public_only=True)
    if nav_items:
        return RedirectResponse(url=f"/{nav_items[0].slug}", status_code=302)
    pages = await visible_pages(admin, org.id, role=None)
    return templates.TemplateResponse(
        request,
        "home_featured.html",
        {
            "org": org,
            "org_handle": handle,
            "pages": pages,
            "page_nav": nav_items,
            "current_user": current_user,
        },
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def public_page(
    slug: str, request: Request, admin: AdminSession, current_user: OptionalCurrentUser
) -> HTMLResponse:
    handle: str = settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    org = await org_by_handle(admin, handle)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    page = await PageRepository(admin, org.id).by_slug(slug)
    if page is None or page.visibility != PageVisibility.public:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    body = render_markdown(page.content)
    nav_items = await PageNavRepository(admin, org.id).nav_items(public_only=True)
    return templates.TemplateResponse(
        request,
        "public_page.html",
        {
            "page": page,
            "body": body,
            "org": org,
            "page_nav": nav_items,
            "current_user": current_user,
        },
    )
