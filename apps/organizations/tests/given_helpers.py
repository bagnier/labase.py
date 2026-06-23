"""Membership helpers for test setup, via the supabase service-role client.

These writes go through PostgREST: they are committed outside the test transaction —
the affected orgs must be tracked via track_org_id().
"""

from typing import cast

from apps.shared.persistence.supabase import get_admin_supabase


def orgs_for_user(user_id: str) -> list[dict]:
    """Returns org rows (id, name, handle, role) for a user via the service-role client."""
    result = (
        get_admin_supabase()
        .table("memberships")
        .select("role, organizations(id, name, handle)")
        .eq("auth_user_id", user_id)
        .order("created_at")
        .execute()
    )
    return [
        {
            "id": row["organizations"]["id"],
            "name": row["organizations"]["name"],
            "handle": row["organizations"]["handle"],
            "role": row["role"],
        }
        for row in cast(list[dict], result.data)
    ]


def add_membership(org_id: str, user_id: str, role: str = "member") -> None:
    get_admin_supabase().table("memberships").insert(
        {"org_id": org_id, "auth_user_id": user_id, "role": role}
    ).execute()


def set_membership_role(org_id: str, user_id: str, role: str) -> None:
    get_admin_supabase().table("memberships").update({"role": role}).eq("org_id", org_id).eq(
        "auth_user_id", user_id
    ).execute()


def create_org_for_user(name: str, user_id: str) -> dict:
    """Create an org + owner membership via the service-role client.

    Committed outside any transaction — Supabase Storage RLS needs the org in the committed DB.
    Returns {"id": str, "handle": str}.
    """
    from apps.shared.slug_registry import slugify

    handle = slugify(name) or "org"
    client = get_admin_supabase()
    client.table("organizations").delete().eq("handle", handle).execute()
    result = client.table("organizations").insert({"name": name, "handle": handle}).execute()
    org_id = cast(list[dict], result.data)[0]["id"]
    client.table("memberships").insert(
        {"org_id": org_id, "auth_user_id": user_id, "role": "owner"}
    ).execute()
    return {"id": org_id, "handle": handle}


def delete_org(org_id: str) -> None:
    get_admin_supabase().table("organizations").delete().eq("id", org_id).execute()
