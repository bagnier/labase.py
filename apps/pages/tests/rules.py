"""Who may do what to a page and to the navigation.

Drafts are collaborative; publishing, changing a published page and the navigation are the
owners'. ``published`` stands for any visibility but ``draft``: the policy tells only those two
apart.
"""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.authorization import Action, Fields, Org, Route, Rule, RuleBook

_VISIBILITY = {"draft": "draft", "published": "members"}

EDIT = Action(
    name="edit",
    sql="update pages set title = 'Changed' where id = :page_id returning id",
    route=Route("PATCH", "/pages/{slug}", {"title": "Changed"}),
)
DELETE = Action(
    name="delete",
    sql="delete from pages where id = :page_id returning id",
    route=Route("DELETE", "/pages/{slug}"),
)
PUBLISH = Action(
    name="publish",
    sql="update pages set visibility = 'members' where id = :page_id returning id",
    route=Route("POST", "/pages/{slug}/visibility", {"visibility": "members"}),
)
ADD_TO_NAV = Action(
    name="add-to-nav",
    sql="insert into page_nav_items (org_id, page_id) values (:org_id, :page_id) returning id",
    route=Route("POST", "/pages/nav", {"slug": "{slug}"}),
)


async def _seed_in_db(session: AsyncSession, org: Org) -> dict[str, Fields]:
    statement = text(
        "insert into pages (org_id, user_id, title, slug, visibility)"
        " values (:org_id, :user_id, 'T', :slug, CAST(:visibility AS page_visibility))"
        " returning id::text"
    )
    return {
        state: {
            "slug": state,
            "page_id": await session.scalar(
                statement,
                {
                    "org_id": org.id,
                    "user_id": org.people["owner"],
                    "slug": state,
                    "visibility": visibility,
                },
            ),
        }
        for state, visibility in _VISIBILITY.items()
    }


def _seed_through_routes(owner: httpx.Client, org: Org) -> dict[str, Fields]:
    pages = f"/{org.handle}/pages"
    targets = {}
    for state, visibility in _VISIBILITY.items():
        created = owner.post(pages, json={"title": state, "slug": state}).raise_for_status()
        owner.post(
            f"{pages}/{state}/visibility", json={"visibility": visibility}
        ).raise_for_status()
        targets[state] = {"slug": state, "page_id": created.json()["id"]}
    return targets


PAGES = RuleBook(
    rules=[
        Rule("pages", "member", EDIT, "draft", allowed=True),
        Rule("pages", "member", DELETE, "draft", allowed=True),
        Rule("pages", "member", EDIT, "published", allowed=False),
        Rule("pages", "member", DELETE, "published", allowed=False),
        Rule("pages", "member", PUBLISH, "draft", allowed=False),
        Rule("pages", "owner", EDIT, "published", allowed=True),
        Rule("pages", "owner", DELETE, "published", allowed=True),
        Rule("pages", "owner", PUBLISH, "draft", allowed=True),
        Rule("page_nav_items", "member", ADD_TO_NAV, "published", allowed=False),
        Rule("page_nav_items", "owner", ADD_TO_NAV, "published", allowed=True),
    ],
    seed_in_db=_seed_in_db,
    seed_through_routes=_seed_through_routes,
)
