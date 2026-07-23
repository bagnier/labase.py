"""How the pages (CMS) context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the public
view router and the org-scoped management router, claims the ``pages`` slug, answers the
dashboard ``OverviewQuery`` and the server-wide ``ConsoleOverviewQuery``, and seeds a
public Welcome page (in the public nav) on ``OrganizationCreated``.
"""

import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrganizationCreated
from apps.organizations.contract.fullpage import OrgNavItem, OrgNavQuery
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import seed_org_welcome
from apps.pages.contract.events import (
    PageCreated,
    PageDeleted,
    PagePublishedMembers,
    PagePublishedPublic,
    PageSlugChanged,
    PageUnpublished,
    PageUpdated,
)
from apps.pages.domain.models import Page, PageVisibility
from apps.pages.infra.repository import PageNavRepository, PageRepository
from apps.pages.infra.router import public_router, router
from apps.shared.host import AppManifest, Host, MountPhase, NavItem
from apps.shared.persistence.repository import count_all
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.shared.text import overview_from_count

PHASE = MountPhase.ORG

_RECENT = 3

_WELCOME_TITLE = "Welcome"
_WELCOME_SLUG = "welcome"
_WELCOME_BODY = (Path(__file__).parent / "welcome_page.md").read_text()


def mount(host: Host) -> None:
    host.register_app(
        AppManifest(
            settings=_declare_settings(),
            provides=[(ConsoleOverviewQuery, _console_overview)],
            routers=[(router, ORG_PREFIX), (public_router, "")],
            nav=[NavItem("Pages", "note-pencil", "pages", "/pages", order=40)],
            emits=[
                PageCreated,
                PageDeleted,
                PageUpdated,
                PageSlugChanged,
                PagePublishedMembers,
                PagePublishedPublic,
                PageUnpublished,
            ],
            consumes_when_enabled=[(OrganizationCreated, "pages_welcome", _seed)],
            provides_when_enabled=[
                (OverviewQuery, _overview),
                (OrgNavQuery, _org_nav),
            ],
        )
    )


def _declare_settings() -> SettingsDeclaration:
    return SettingsDeclaration(
        app_name="pages",
        defs=[
            feature_switch(),
            SettingDef(
                "default_visibility",
                "string",
                "draft",
                "Visibility a new page starts at — one of: draft, members, public",
            ),
        ],
        supabase=SupabaseLink("Browse pages in Supabase", table="pages"),
    )


async def _overview(query: OverviewQuery) -> Overview:
    pages = await PageRepository(query.session, query.org_id).all()
    n = len(pages)
    lines = overview_from_count(n, "page", "No pages yet")
    return Overview(
        key="pages",
        title="Pages",
        icon="file-text",
        href="pages",
        template="pages/_overview.html",
        data={"lines": lines, "recent": [p.title for p in pages[:_RECENT]]},
    )


async def _seed(session: AsyncSession, event: OrganizationCreated) -> None:
    """Seed a public Welcome page, listed in the public nav.

    Public so that pointing ``public.featured_org_handle`` at the org makes it the site home; in
    the nav so ``/`` redirects straight to it. A durable async consumer of ``OrganizationCreated``,
    suppressed in the test schema (via ``seed_org_welcome``), so it never runs under e2e.
    """
    await seed_org_welcome(session, event.org_id, _seed_welcome)


async def _seed_welcome(session: AsyncSession, org_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    repo = PageRepository(session, org_id)
    if await repo.slug_taken(_WELCOME_SLUG):
        return
    page = await repo.add(owner_id, _WELCOME_TITLE, _WELCOME_SLUG, _WELCOME_BODY)
    page.visibility = PageVisibility.public
    await PageNavRepository(session, org_id).add(page.id)


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await count_all(query.session, Page)
    lines = overview_from_count(total, "page", "No pages yet")
    return ConsoleOverview(key="pages", title="Pages", icon="file-text", data={"lines": lines})


async def _org_nav(query: OrgNavQuery) -> list[OrgNavItem]:
    all_items = await PageNavRepository(query.session, query.org_id).nav_items(public_only=False)
    return [
        OrgNavItem(slug=p.slug, title=p.title, href=f"pages/{p.slug}")
        for p in all_items
        if p.visibility == PageVisibility.members
    ]
