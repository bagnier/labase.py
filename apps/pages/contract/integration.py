"""How the pages (CMS) context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the public
view router and the org-scoped management router, claims the ``pages`` slug, answers the
dashboard ``OverviewQuery`` and the server-wide ``ConsoleOverviewQuery``.
"""

from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.fullpage import OrgNavItem, OrgNavQuery
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.pages.contract import settings
from apps.pages.domain.models import PageVisibility
from apps.pages.infra.repository import PageNavRepository, PageRepository, count_all
from apps.pages.infra.router import public_router, router
from apps.settings.contract.overviews import ConsoleOverview, ConsoleOverviewQuery
from apps.settings.contract.settings import (
    SettingDef,
    SettingsChanged,
    SupabaseLink,
    declare_app_settings,
    feature_switch,
    get_app_settings,
)
from apps.shared.host import Host, NavItem
from apps.shared.text import overview_from_count

_RECENT = 3


def mount(host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    _declare_settings()
    host.reserve("pages")  # reserved even when disabled, to keep the slug from being squatted
    if not get_app_settings("pages").enabled:
        return
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    host.app.include_router(router, prefix=ORG_PREFIX)
    host.app.include_router(public_router)
    host.register_nav(NavItem("Pages", "note-pencil", "pages", "/pages", order=25))
    host.events.on(OverviewQuery, _overview)
    host.events.on(OrgNavQuery, _org_nav)


def _declare_settings() -> None:
    settings.group = declare_app_settings(
        "pages",
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


async def _console_overview(query: ConsoleOverviewQuery) -> ConsoleOverview:
    total = await count_all(query.session)
    lines = overview_from_count(total, "page", "No pages yet")
    return ConsoleOverview(key="pages", title="Pages", icon="file-text", data={"lines": lines})


async def _org_nav(query: OrgNavQuery) -> list[OrgNavItem]:
    all_items = await PageNavRepository(query.session, query.org_id).nav_items(public_only=False)
    return [
        OrgNavItem(slug=p.slug, title=p.title, href=f"pages/{p.slug}")
        for p in all_items
        if p.visibility == PageVisibility.members
    ]
