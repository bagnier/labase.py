"""Organizations' fullpage-context slice: the user's orgs, each with its org-specific nav.

Registered as a fullpage provider at organizations' ``mount()`` and collected by
:func:`apps.shared.page.fullpage_context`. For each org, :func:`provide_org_nav` fires
:class:`OrgNavQuery` — "collect this org's specific nav items" — and any app can answer
via ``host.contribs.provide(OrgNavQuery, handler)``, returning a list of :class:`OrgNavItem`
(e.g. ``pages`` returns the org's published pages).

This is the *org-specific* nav. The *global* app links (Todos, Files, …) are not here:
they are static ``NavItem``\\ s registered via ``host.register_nav`` and seeded once by
the collector as ``nav_items``.
"""

import uuid
from dataclasses import dataclass, field

import structlog

from apps.organizations.contract.collect import OrgMemberQuery
from apps.organizations.contract.queries import get_user_orgs
from apps.shared.contribs import contribs
from apps.shared.page import FullpageQuery

log = structlog.get_logger("labase.organizations.fullpage")


@dataclass(frozen=True)
class OrgNavItem:
    """An org-specific sidebar link, contributed by an app answering :class:`OrgNavQuery`."""

    slug: str
    title: str
    href: str
    icon: str = "file-text"


@dataclass(frozen=True)
class OrgNavQuery(OrgMemberQuery):
    """Collected per org by :func:`provide_org_nav`: "give me this org's specific nav
    items". Handlers return ``list[OrgNavItem]`` (one collect grammar — see
    :mod:`apps.organizations.contract.collect`)."""


@dataclass
class NavOrg:
    """An org as the sidebar renders it: identity + its org-specific nav items."""

    id: uuid.UUID
    name: str
    handle: str
    is_owner: bool
    extra_nav: list[OrgNavItem] = field(default_factory=list)


async def provide_org_nav(query: FullpageQuery) -> dict:
    """Fullpage slice ``org_nav``: the user's orgs, each with its org-specific nav.

    Fetches the user's orgs, then for each fires :class:`OrgNavQuery` to collect the
    org-specific nav items other apps contribute. Relies on Postgres RLS (the request
    session carries the user's context): ``organizations: member read`` returns exactly
    the user's orgs.
    """
    if query.user is None:
        return {"nav": []}
    try:
        orgs = await get_user_orgs(query.session, uuid.UUID(query.user.id))
    except Exception:
        log.exception("organizations.org_nav_load_failed")
        return {"nav": []}
    nav_orgs = []
    for o in orgs:
        results = await contribs.collect(OrgNavQuery(query.session, o.id, o.is_owner))
        extra_nav = [item for chunk in results for item in chunk]
        nav_orgs.append(
            NavOrg(id=o.id, name=o.name, handle=o.handle, is_owner=o.is_owner, extra_nav=extra_nav)
        )
    return {"nav": nav_orgs}
