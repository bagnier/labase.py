import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from apps.pages.domain.models import NavItemRead, Page, PageRead, PageVisibility
from apps.pages.domain.render import render_markdown
from apps.pages.infra.repository import PageNavRepository, PageRepository, visible_pages


@dataclass
class PublicPageView:
    page: PageRead
    body: str


async def get_public_nav(session: AsyncSession, org_id: uuid.UUID) -> list[NavItemRead]:
    return await PageNavRepository(session, org_id).nav_items(public_only=True)


async def get_public_page(
    session: AsyncSession, org_id: uuid.UUID, slug: str
) -> PublicPageView | None:
    page = await PageRepository(session, org_id).by_slug(slug)
    if page is None or page.visibility != PageVisibility.public:
        return None
    return PublicPageView(
        page=PageRead.model_validate(page),
        body=render_markdown(page.content),
    )


async def get_public_pages(session: AsyncSession, org_id: uuid.UUID) -> list[Page]:
    return await visible_pages(session, org_id, role=None)
