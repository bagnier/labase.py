"""Helpers admin memberships pour les tests, via le client supabase service-role.

Ces écritures passent par PostgREST : elles sont commitées hors de la transaction
de test — les orgs concernées doivent être trackées via track_org_id().
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
