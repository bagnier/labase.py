"""Admin membership helpers for tests, via the supabase service-role client.

These writes go through PostgREST: they are committed outside the test transaction —
the affected orgs must be tracked via track_org_id().
"""

from typing import cast

from app.shared.persistence.supabase import get_admin_supabase


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


def memberships_for_user(user_id: str) -> list[dict]:
    result = (
        get_admin_supabase().table("memberships").select("*").eq("auth_user_id", user_id).execute()
    )
    return cast(list[dict], result.data)
