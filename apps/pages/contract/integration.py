"""How the pages (CMS) context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the public
view router and the org-scoped management router, claims the ``pages`` slug, answers the
dashboard ``OverviewQuery`` and the server-wide ``ConsoleOverviewQuery``, and seeds a
public Welcome page (in the public nav) on ``OrgCreated``.
"""

from pathlib import Path

from apps.console.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.events import OrgCreated
from apps.organizations.contract.fullpage import OrgNavItem, OrgNavQuery
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.organizations.contract.queries import get_org_owner_id
from apps.pages.domain.models import Page, PageVisibility
from apps.pages.infra.repository import PageNavRepository, PageRepository
from apps.pages.infra.router import public_router, router
from apps.shared.host import Host, NavItem
from apps.shared.persistence.database import admin_session_factory
from apps.shared.persistence.repository import count_all
from apps.shared.settings import SettingDef, SettingsDeclaration, SupabaseLink, feature_switch
from apps.shared.text import overview_from_count

_RECENT = 3

_WELCOME_TITLE = "Welcome"
_WELCOME_SLUG = "welcome"
_WELCOME_BODY = (Path(__file__).parent / "welcome_page.md").read_text()


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    settings = host.register_settings(_declare_settings())
    host.reserve("pages")  # reserved even when disabled, to keep the slug from being squatted
    if not settings.enabled:
        return
    host.app.include_router(router, prefix=ORG_PREFIX)
    host.app.include_router(public_router)
    host.register_nav(NavItem("Pages", "note-pencil", "pages", "/pages", order=40))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgNavQuery, _org_nav)
    host.events.on(OrgCreated, _seed)


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


async def _seed(event: OrgCreated) -> None:
    """Seed a public Welcome page, listed in the public nav.

    Public so that pointing ``public.featured_org_handle`` at the org makes it the site
    home; in the nav so ``/`` redirects straight to it. Production-only: ``OrgCreated``
    is suppressed in the test schema, so this never runs under the e2e drivers.
    """
    async with admin_session_factory()() as session:
        owner_id = await get_org_owner_id(session, event.org_id)
        if owner_id is None:
            return
        repo = PageRepository(session, event.org_id)
        if await repo.slug_taken(_WELCOME_SLUG):
            return
        page = await repo.add(owner_id, _WELCOME_TITLE, _WELCOME_SLUG, _WELCOME_BODY)
        page.visibility = PageVisibility.public
        await PageNavRepository(session, event.org_id).add(page.id)
        await session.commit()


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
