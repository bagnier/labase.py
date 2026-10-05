"""GoTrue helpers for test setup, via the supabase service-role client."""

from supabase_auth.types import User

from apps.shared.persistence.supabase import get_admin_supabase
from tests.e2e.sql_setup import run_sql


def find_users(email: str) -> list[User]:
    """GoTrue users with exactly this email, filtered here: the admin API returns everyone, and
    deleting them all would block on rows the open test transaction locks."""
    supabase = get_admin_supabase().auth.admin
    found: list[User] = []
    page = 1
    while True:
        users = supabase.list_users(page=page, per_page=1000)
        found.extend(u for u in users if u.email == email)
        if len(users) < 1000:
            return found
        page += 1


def delete_user_if_exists(email: str) -> None:
    for user in find_users(email):
        delete_user(user.id)


def create_user(email: str, password: str) -> str:
    resp = get_admin_supabase().auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": True}
    )
    assert resp.user, f"create_user({email!r}) returned no user"
    return resp.user.id


def delete_user(uid: str) -> None:
    """Delete the GoTrue user and its journal facts: the trigger's committed ``UserCreated`` has
    no FK to cascade, and would be re-delivered by every later drain."""
    get_admin_supabase().auth.admin.delete_user(uid)
    run_sql("DELETE FROM business_events WHERE user_id = :uid", {"uid": uid})


def set_admin_role(uid: str) -> None:
    """Set the admin role; call it before sign-in, since the token carries ``app_metadata``."""
    get_admin_supabase().auth.admin.update_user_by_id(uid, {"app_metadata": {"role": "admin"}})


def clear_all_admin_roles() -> None:
    """Remove every admin role, for a bootstrap scenario: test isolation does not reach
    ``auth.users``."""
    admin = get_admin_supabase().auth.admin
    page = 1
    while True:
        users = admin.list_users(page=page, per_page=1000)
        for u in users:
            if u.deleted_at:
                continue  # soft-deleted: its identities do not round-trip through the API
            if (u.app_metadata or {}).get("role"):
                admin.update_user_by_id(u.id, {"app_metadata": {"role": None}})
        if len(users) < 1000:
            return
        page += 1


def user_id_for_email(email: str) -> str:
    users = find_users(email)
    assert users, f"User {email!r} not found in Supabase"
    return users[0].id


def create_unconfirmed_user(email: str, password: str) -> str:
    """Through the admin API: locally, signup autoconfirms."""
    resp = get_admin_supabase().auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": False}
    )
    assert resp.user, f"create_unconfirmed_user({email!r}) returned no user"
    return resp.user.id
