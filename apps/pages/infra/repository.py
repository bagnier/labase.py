import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.contract.current import OrgRole
from apps.pages.domain.models import NavCandidate, NavItemRead, Page, PageNavItem, PageVisibility
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository, PositionedRepository


class PageRepository(OrgScopedRepository[Page]):
    model = Page
    default_order = Page.created_at.desc()

    async def by_slug(self, slug: str) -> Page | None:
        return await self.session.scalar(
            select(Page).where(Page.org_id == self.org_id, Page.slug == slug)
        )

    async def by_id(self, page_id: uuid.UUID) -> Page | None:
        return await self.session.scalar(
            select(Page).where(Page.org_id == self.org_id, Page.id == page_id)
        )

    async def slug_taken(self, slug: str, exclude_id: uuid.UUID | None = None) -> bool:
        q = select(Page.id).where(Page.org_id == self.org_id, Page.slug == slug)
        if exclude_id is not None:
            q = q.where(Page.id != exclude_id)
        return await self.session.scalar(q) is not None

    async def add(self, user_id: uuid.UUID, title: str, slug: str, content: str) -> Page:
        page = Page(
            org_id=self.org_id,
            user_id=user_id,
            title=title,
            slug=slug,
            content=content,
            visibility=PageVisibility.draft,
            created_at=clock.now(),
        )
        self.session.add(page)
        await self.session.flush()
        return page


async def visible_pages(
    session: AsyncSession, org_id: uuid.UUID, *, role: OrgRole | None
) -> list[Page]:
    """Pages visible to the requester: members/owners see every page, anonymous
    visitors only ``public`` ones."""
    q = select(Page).where(Page.org_id == org_id).order_by(Page.created_at.desc())
    if role is None:
        q = q.where(Page.visibility == PageVisibility.public)
    return list(await session.scalars(q))


async def search_visible_pages(
    session: AsyncSession, org_id: uuid.UUID, query: str, *, role: OrgRole | None
) -> list[Page]:
    """Fulltext search over the visible pages (title + body), ranked by relevance.

    Uses the generated ``search_vector`` (GIN-indexed) with ``websearch_to_tsquery`` so
    natural queries (quoted phrases, ``or``) work; falls back to recency for ties. Same
    visibility rules as :func:`visible_pages`."""
    tsq = func.websearch_to_tsquery("english", query)
    q = (
        select(Page)
        .where(Page.org_id == org_id, Page.search_vector.op("@@")(tsq))
        .order_by(func.ts_rank(Page.search_vector, tsq).desc(), Page.created_at.desc())
    )
    if role is None:
        q = q.where(Page.visibility == PageVisibility.public)
    return list(await session.scalars(q))


class PageNavRepository(PositionedRepository[PageNavItem]):
    model = PageNavItem
    default_order = PageNavItem.position.asc()
    position_key = "page_id"

    async def candidates(self) -> list[NavCandidate]:
        """All published pages with their current nav status, nav items first."""
        nav_rows = await self.all()
        nav_by_page: dict[uuid.UUID, PageNavItem] = {n.page_id: n for n in nav_rows}
        pages = list(
            await self.session.scalars(
                select(Page)
                .where(Page.org_id == self.org_id, Page.visibility != PageVisibility.draft)
                .order_by(Page.title)
            )
        )
        in_nav = [
            NavCandidate(
                page_id=p.id,
                slug=p.slug,
                title=p.title,
                visibility=p.visibility,
                in_nav=True,
                position=nav_by_page[p.id].position,
            )
            for p in pages
            if p.id in nav_by_page
        ]
        not_in_nav = [
            NavCandidate(
                page_id=p.id,
                slug=p.slug,
                title=p.title,
                visibility=p.visibility,
                in_nav=False,
                position=None,
            )
            for p in pages
            if p.id not in nav_by_page
        ]
        in_nav.sort(key=lambda c: c.position or 0)
        return in_nav + not_in_nav

    async def nav_items(self, *, public_only: bool = False) -> list[NavItemRead]:
        """Ordered nav items for page rendering. If public_only, exclude members-only pages."""
        rows = await self.all()
        page_ids = [r.page_id for r in rows]
        if not page_ids:
            return []
        pages_map: dict[uuid.UUID, Page] = {
            p.id: p for p in await self.session.scalars(select(Page).where(Page.id.in_(page_ids)))
        }
        result = []
        for row in rows:
            page = pages_map.get(row.page_id)
            if page is None:
                continue
            if public_only and page.visibility != PageVisibility.public:
                continue
            result.append(
                NavItemRead(
                    page_id=page.id,
                    slug=page.slug,
                    title=page.title,
                    visibility=page.visibility,
                )
            )
        return result

    async def add(self, page_id: uuid.UUID) -> PageNavItem:
        max_pos = await self.session.scalar(
            select(func.max(PageNavItem.position)).where(PageNavItem.org_id == self.org_id)
        )
        item = PageNavItem(
            org_id=self.org_id,
            page_id=page_id,
            position=(max_pos or 0) + 1,
        )
        return await self.save(item)

    async def remove(self, page_id: uuid.UUID) -> None:
        item = await self.session.scalar(
            select(PageNavItem).where(
                PageNavItem.org_id == self.org_id,
                PageNavItem.page_id == page_id,
            )
        )
        if item is not None:
            await self.delete(item)
