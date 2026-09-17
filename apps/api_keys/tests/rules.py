"""Who may see, issue and revoke an org's API keys: its owners alone."""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.authorization import Action, Fields, Org, Route, Rule, RuleBook

READ = Action(
    name="read",
    sql="select id from api_keys where id = :key_id",
    route=Route("GET", "/api-keys"),
)
ISSUE = Action(
    name="issue",
    sql="insert into api_keys (org_id, created_by, name, prefix, key_hash)"
    " values (:org_id, :me, 'k', 'lbk_new', gen_random_uuid()::text) returning id",
    route=Route("POST", "/api-keys", {"name": "k"}),
)
REVOKE = Action(
    name="revoke",
    sql="update api_keys set revoked_at = now() where id = :key_id returning id",
    route=Route("DELETE", "/api-keys/{key_id}"),
)


async def _seed_in_db(session: AsyncSession, org: Org) -> dict[str, Fields]:
    key_id = await session.scalar(
        text(
            "insert into api_keys (org_id, created_by, name, prefix, key_hash)"
            " values (:org_id, :owner, 'k', 'lbk_old', gen_random_uuid()::text) returning id::text"
        ),
        {"org_id": org.id, "owner": org.people["owner"]},
    )
    return {"key": {"key_id": key_id}}


def _seed_through_routes(owner: httpx.Client, org: Org) -> dict[str, Fields]:
    issued = owner.post(f"/{org.handle}/api-keys", json={"name": "k"}).raise_for_status()
    return {"key": {"key_id": issued.json()["id"]}}


API_KEYS = RuleBook(
    rules=[
        Rule("api_keys", "member", READ, "key", allowed=False),
        Rule("api_keys", "owner", READ, "key", allowed=True),
        Rule("api_keys", "member", ISSUE, "key", allowed=False),
        Rule("api_keys", "owner", ISSUE, "key", allowed=True),
        Rule("api_keys", "member", REVOKE, "key", allowed=False),
        Rule("api_keys", "owner", REVOKE, "key", allowed=True),
    ],
    seed_in_db=_seed_in_db,
    seed_through_routes=_seed_through_routes,
)
