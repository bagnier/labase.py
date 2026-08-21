import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from apps.pages.domain.models import NavItemRead, Page, PageDocumentRead, PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import PageNavRepository, PageRepository, visible_pages


async def get_public_nav(session: AsyncSession, org_id: uuid.UUID) -> list[NavItemRead]:
    return await PageNavRepository(session, org_id).nav_items(public_only=True)


async def get_public_page(
    session: AsyncSession, org_id: uuid.UUID, slug: str
) -> PageDocumentRead | None:
    """A public page as a document — its Markdown, its rendered HTML, and ``can_edit`` false:
    whoever reads a page here is anonymous, and never may."""
    page = await PageRepository(session, org_id).by_slug(slug)
    if page is None or page.visibility != PageVisibility.public:
        return None
    return PageDocumentRead.of(page, body_html=render_markdown(page.content), can_edit=False)


async def get_public_pages(session: AsyncSession, org_id: uuid.UUID) -> list[Page]:
    return await visible_pages(session, org_id, role=None)
