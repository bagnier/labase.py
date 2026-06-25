import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from apps.auth.contract.current import OptionalCurrentUser
from apps.pages.domain.models import PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import (
    PageNavRepository,
    PageRepository,
    org_by_handle,
    role_in_org,
    visible_pages,
)
from apps.public.contract import settings
from apps.shared.http.templates import templates
from apps.shared.persistence.database import AdminSession

router = APIRouter(tags=["public"])


@router.get("/", response_class=HTMLResponse)
async def index(
    request: Request, admin: AdminSession, current_user: OptionalCurrentUser
) -> HTMLResponse:
    handle: str = settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        return templates.TemplateResponse(request, "home.html")
    org = await org_by_handle(admin, handle)
    if org is None:
        return templates.TemplateResponse(request, "home.html")
    pages = await visible_pages(admin, org.id, role=None)
    role = await role_in_org(admin, org.id, uuid.UUID(current_user.id)) if current_user else None
    nav_items = await PageNavRepository(admin, org.id).nav_items(public_only=(role is None))
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
        raise HTTPException(404)
    org = await org_by_handle(admin, handle)
    if org is None:
        raise HTTPException(404)
    page = await PageRepository(admin, org.id).by_slug(slug)
    if page is None or page.visibility != PageVisibility.public:
        raise HTTPException(404)
    body = render_markdown(page.content)
    role = await role_in_org(admin, org.id, uuid.UUID(current_user.id)) if current_user else None
    nav_items = await PageNavRepository(admin, org.id).nav_items(public_only=(role is None))
    return templates.TemplateResponse(
        request,
        "public_page.html",
        {"page": page, "body": body, "org": org, "page_nav": nav_items},
    )
