import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.organizations.domain.models import Membership, Organization, OrgRole
from apps.pages.domain.models import Page, PageVisibility
from apps.shared import clock
from apps.shared.persistence.repository import OrgScopedRepository


class PageRepository(OrgScopedRepository[Page]):
    model = Page

    async def all(self) -> list[Page]:
        return list(
            await self.session.scalars(
                select(Page).where(Page.org_id == self.org_id).order_by(Page.created_at.desc())
            )
        )

    async def by_slug(self, slug: str) -> Page | None:
        return await self.session.scalar(
            select(Page).where(Page.org_id == self.org_id, Page.slug == slug)
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


async def org_by_handle(session: AsyncSession, handle: str) -> Organization | None:
    """Resolve an org by its URL handle, ignoring RLS — used by the public view route."""
    return await session.scalar(select(Organization).where(Organization.handle == handle))


async def is_member(session: AsyncSession, org_id: uuid.UUID, auth_user_id: uuid.UUID) -> bool:
    found = await session.scalar(
        select(Membership.role).where(
            Membership.org_id == org_id, Membership.auth_user_id == auth_user_id
        )
    )
    return found is not None


async def role_in_org(
    session: AsyncSession, org_id: uuid.UUID, auth_user_id: uuid.UUID
) -> OrgRole | None:
    return await session.scalar(
        select(Membership.role).where(
            Membership.org_id == org_id, Membership.auth_user_id == auth_user_id
        )
    )


async def visible_pages(
    session: AsyncSession, org_id: uuid.UUID, *, role: OrgRole | None
) -> list[Page]:
    """Pages visible to the requester: members/owners see every page, anonymous
    visitors only ``public`` ones."""
    q = select(Page).where(Page.org_id == org_id).order_by(Page.created_at.desc())
    if role is None:
        q = q.where(Page.visibility == PageVisibility.public)
    return list(await session.scalars(q))


async def count_all(session: AsyncSession) -> int:
    """Server-wide page count, across every organisation (console overview)."""
    return int(await session.scalar(select(func.count()).select_from(Page)) or 0)
