"""Membership helpers for test setup, via SQLAlchemy against the active schema.

These writes go through SQLAlchemy (not PostgREST, which is pinned to ``public``) so they
land in ``SUPABASE_DATABASE_SCHEMA`` — the schema the app reads. They are committed outside the test
transaction — the affected orgs must be tracked via track_org_id().
"""

from tests.e2e.sql_setup import run_sql


def orgs_for_user(user_id: str) -> list[dict]:
    """Returns org rows (id, name, handle, role) for a user, ordered by membership creation."""
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
    # Setup escape hatch: forces role states the app forbids (e.g. demoting a sole owner),
    # so it must bypass the last-owner DB trigger just as it bypasses RLS by running as admin.
    run_sql(
        "update memberships set role = :role where org_id = :org and user_id = :uid",
        {"role": role, "org": org_id, "uid": user_id},
        bypass_triggers=True,
    )


def create_org_for_user(name: str, user_id: str) -> dict:
    """Create an org + owner membership.

    Committed outside any transaction — Supabase Storage RLS needs the org in the committed DB.
    Returns {"id": str, "handle": str}.
    """
    from apps.shared.integration.slugs import slugify

    handle = slugify(name) or "org"
    run_sql("delete from organizations where handle = :handle", {"handle": handle})
    rows = run_sql(
        "insert into organizations (name, handle) values (:name, :handle) returning id::text as id",
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
