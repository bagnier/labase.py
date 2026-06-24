"""How the pages (CMS) context plugs into the running app.

Single composition entry (:func:`mount`, called from :mod:`apps.main`): mounts the public
view router and the org-scoped management router, claims the ``pages`` slug, answers the
dashboard ``OverviewQuery`` and the server-wide ``ConsoleOverviewQuery``.
"""

from fastapi import FastAPI

from apps.organizations.contract import ORG_PREFIX
from apps.organizations.contract.overviews import Overview, OverviewQuery
from apps.pages.contract import settings
from apps.pages.infra.repository import PageRepository, count_all
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

_RECENT = 3


def mount(app: FastAPI, host: Host) -> None:
    # Console presence is kept even when disabled, so an admin can see and re-enable the app.
    host.events.on(ConsoleOverviewQuery, _console_overview)
    _declare_settings()
    host.reserve("pages")  # reserved even when disabled, to keep the slug from being squatted
    if not get_app_settings("pages").enabled:
        return
    settings.read()
    host.events.on(SettingsChanged, settings.reload)
    app.include_router(public_router)
    app.include_router(router, prefix=ORG_PREFIX)
    host.register_nav(NavItem("Pages", "file-text", "pages", "/pages", order=25))
    host.events.on(OverviewQuery, _overview)


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
    lines = [f"{n} page" + ("s" if n != 1 else "")] if pages else ["No pages yet"]
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
    lines = [f"{total} page" + ("s" if total != 1 else "")] if total else ["No pages yet"]
    return ConsoleOverview(key="pages", title="Pages", icon="file-text", data={"lines": lines})
