"""Membership setup through SQLAlchemy, not PostgREST (pinned to ``public``), so it lands in the
app's schema. Committed outside the test transaction: track the orgs with track_org_id().
"""

from tests.e2e.sql_setup import run_sql


def orgs_for_user(user_id: str) -> list[dict]:
    """``(id, name, handle, role)`` per org, by membership age."""
    return run_sql(
        """
        select o.id::text as id, o.name, o.handle, m.role
        from memberships m join organizations o on o.id = m.org_id
        where m.user_id = :uid
        order by m.created_at
        """,
        {"uid": user_id},
        fetch=True,
    )


def add_membership(org_id: str, user_id: str, role: str = "member") -> None:
    run_sql(
        "insert into memberships (org_id, user_id, role) values (:org, :uid, :role)",
        {"org": org_id, "uid": user_id, "role": role},
    )


def set_membership_role(org_id: str, user_id: str, role: str) -> None:
    # Forces states the app forbids (a sole owner demoted): bypasses the last-owner trigger.
    run_sql(
        "update memberships set role = :role where org_id = :org and user_id = :uid",
        {"role": role, "org": org_id, "uid": user_id},
        bypass_triggers=True,
    )


def create_org_for_user(name: str, user_id: str) -> dict:
    """Create a committed org and its owner (Storage RLS reads committed rows); returns
    ``{"id", "handle"}``.

    Marked ``is_personal``, standing in for the sign-up org: else a later drain would create one
    for the user's ``UserCreated``, on a rolled-back connection other writes cannot see.
    """
    from apps.shared.integration.slugs import slugify

    handle = slugify(name) or "org"
    run_sql("delete from organizations where handle = :handle", {"handle": handle})
    rows = run_sql(
        "insert into organizations (name, handle, is_personal) values (:name, :handle, true)"
        " returning id::text as id",
        {"name": name, "handle": handle},
        fetch=True,
    )
    org_id = rows[0]["id"]
    run_sql(
        "insert into memberships (org_id, user_id, role) values (:org, :uid, 'owner')",
        {"org": org_id, "uid": user_id},
    )
    return {"id": org_id, "handle": handle}


def delete_org(org_id: str) -> None:
    run_sql("delete from organizations where id = :org", {"org": org_id})
