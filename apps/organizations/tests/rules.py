"""Who may change an org, its members and its invitations.

Members read; owners rename, promote, remove, add and invite. A member may still leave on their
own. Keeping an org's last owner is an invariant, not an authorization rule: its trigger answers
it (``test_last_owner_db_guard``).
"""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.authorization import Action, Fields, Org, Route, Rule, RuleBook

RENAME = Action(
    name="rename",
    sql="update organizations set name = 'Changed' where id = :org_id returning id",
    route=Route("PATCH", "", {"name": "Changed"}),
)
PROMOTE = Action(
    name="promote",
    sql="update memberships set role = 'owner'"
    " where org_id = :org_id and user_id = :user_id returning user_id",
    route=Route("PATCH", "/members/{user_id}", {"role": "owner"}),
)
REMOVE = Action(
    name="remove",
    sql="delete from memberships where org_id = :org_id and user_id = :user_id returning user_id",
    route=Route("DELETE", "/members/{user_id}"),
)
LEAVE = Action(
    name="leave",
    sql="delete from memberships where org_id = :org_id and user_id = :me returning user_id",
    route=Route("DELETE", "/members/me"),
)
# Members join by accepting an invitation, never by a route that seats them.
ADD = Action(
    name="add",
    sql="insert into memberships (org_id, user_id) values (:org_id, :user_id) returning user_id",
    route=None,
)
INVITE = Action(
    name="invite",
    sql="insert into org_invitations (org_id, email, invited_by)"
    " values (:org_id, 'invitee@example.com', :me) returning id",
    route=Route("POST", "/invitations", {"email": "invitee@example.com"}),
)
REVOKE = Action(
    name="revoke",
    sql="update org_invitations set status = 'revoked' where id = :invitation_id returning id",
    route=Route("DELETE", "/invitations/{invitation_id}"),
)

_PENDING = "pending@example.com"


def _targets(org: Org, invitation_id: str) -> dict[str, Fields]:
    return {
        "org": {},
        "own-membership": {},
        "new-invitation": {},
        "other-member": {"user_id": org.people["other"]},
        "outsider": {"user_id": org.people["outsider"]},
        "pending-invitation": {"invitation_id": invitation_id},
    }


async def _seed_in_db(session: AsyncSession, org: Org) -> dict[str, Fields]:
    invitation_id = await session.scalar(
        text(
            "insert into org_invitations (org_id, email, invited_by)"
            " values (:org_id, :email, :owner) returning id::text"
        ),
        {"org_id": org.id, "email": _PENDING, "owner": org.people["owner"]},
    )
    return _targets(org, invitation_id)


def _seed_through_routes(owner: httpx.Client, org: Org) -> dict[str, Fields]:
    invited = owner.post(f"/{org.handle}/invitations", json={"email": _PENDING})
    return _targets(org, invited.raise_for_status().json()["id"])


ORGANIZATIONS = RuleBook(
    rules=[
        Rule("organizations", "member", RENAME, "org", allowed=False),
        Rule("organizations", "owner", RENAME, "org", allowed=True),
        Rule("memberships", "member", PROMOTE, "other-member", allowed=False),
        Rule("memberships", "owner", PROMOTE, "other-member", allowed=True),
        Rule("memberships", "member", REMOVE, "other-member", allowed=False),
        Rule("memberships", "owner", REMOVE, "other-member", allowed=True),
        Rule("memberships", "member", LEAVE, "own-membership", allowed=True),
        Rule("memberships", "member", ADD, "outsider", allowed=False),
        Rule("memberships", "owner", ADD, "outsider", allowed=True),
        Rule("org_invitations", "member", INVITE, "new-invitation", allowed=False),
        Rule("org_invitations", "owner", INVITE, "new-invitation", allowed=True),
        Rule("org_invitations", "member", REVOKE, "pending-invitation", allowed=False),
        Rule("org_invitations", "owner", REVOKE, "pending-invitation", allowed=True),
    ],
    seed_in_db=_seed_in_db,
    seed_through_routes=_seed_through_routes,
)
