"""The ``org_nav`` full-page slice: the user's orgs, each with the items apps add through
:class:`OrgNavQuery` (``pages`` adds the published pages). App links shared by every org are
``NavItem``\\ s.
"""

import uuid
from dataclasses import dataclass, field

import structlog

from apps.organizations.contract.collect import OrgMemberQuery
from apps.organizations.contract.queries import get_user_orgs
from apps.shared.integration.contribs import contribs
from apps.shared.integration.fullpage import FullpageQuery

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OrgNavItem:
    slug: str
    title: str
    href: str
    icon: str = "file-text"


@dataclass(frozen=True)
class OrgNavQuery(OrgMemberQuery):
    """Answered with ``list[OrgNavItem]``."""


@dataclass
class NavOrg:
    id: uuid.UUID
    name: str
    handle: str
    is_owner: bool
    extra_nav: list[OrgNavItem] = field(default_factory=list)


async def provide_org_nav(query: FullpageQuery) -> dict:
    """The user's orgs (RLS returns exactly those), each with its collected nav items."""
    if query.user is None:
        return {"nav": []}
    try:
        orgs = await get_user_orgs(query.session, query.user.id)
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
