from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.current import OptionalCurrentUser
from apps.organizations.contract.queries import OrganizationRead, org_by_handle
from apps.pages.contract.public import get_public_nav, get_public_page, get_public_pages
from apps.public.contract.current import PublicSettings
from apps.shared.http import with_etag
from apps.shared.http.templates import templates
from apps.shared.persistence.database import AdminSession
from apps.shared.settings.live import SettingsView

router = APIRouter(tags=["public"])


async def _featured_org(
    admin: AsyncSession, public_settings: SettingsView
) -> OrganizationRead | None:
    """The configured featured org, or ``None`` when unset or unknown — the shared preamble
    of the two public routes (each decides its own bail: home page vs 404)."""
    handle: str = public_settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        return None
    return await org_by_handle(admin, handle)


@router.get("/", response_class=HTMLResponse, response_model=None)
async def index(
    request: Request,
    admin: AdminSession,
    current_user: OptionalCurrentUser,
    public_settings: PublicSettings,
) -> Response:
    org = await _featured_org(admin, public_settings)
    if org is None:
        return with_etag(request, templates.TemplateResponse(request, "home.html"))
    nav_items = await get_public_nav(admin, org.id)
    if nav_items:
        return RedirectResponse(url=f"/{nav_items[0].slug}", status_code=302)
    pages = await get_public_pages(admin, org.id)
    return with_etag(
        request,
        templates.TemplateResponse(
            request,
            "home_featured.html",
            {
                "org": org,
                "org_handle": org.handle,
                "pages": pages,
                "page_nav": nav_items,
                "current_user": current_user,
            },
        ),
    )


@router.get("/{slug}", response_class=HTMLResponse)
async def public_page(
    slug: str,
    request: Request,
    admin: AdminSession,
    current_user: OptionalCurrentUser,
    public_settings: PublicSettings,
) -> Response:
    handle: str = public_settings.featured_org_handle  # type: ignore[assignment]
    if not handle:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    org = await org_by_handle(admin, handle)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    view = await get_public_page(admin, org.id, slug)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    nav_items = await get_public_nav(admin, org.id)
    return with_etag(
        request,
        templates.TemplateResponse(
            request,
            "public_page.html",
            {
                "page": view.page,
                "body": view.body,
                "org": org,
                "page_nav": nav_items,
                "current_user": current_user,
            },
        ),
    )
