"""Admin membership helpers for tests, via the supabase service-role client.

These writes go through PostgREST: they are committed outside the test transaction —
the affected orgs must be tracked via track_org_id().
"""

from typing import cast

from app.shared.persistence.supabase import get_admin_supabase


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
