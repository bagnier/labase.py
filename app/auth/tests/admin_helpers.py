"""Admin GoTrue helpers for tests, via the supabase service-role client."""

from supabase_auth.types import User

from app.shared.persistence.supabase import get_admin_supabase


def find_users(email: str) -> list[User]:
    """Lists GoTrue users with exactly this email.

    The admin API does not filter by email and returns all users: filtering
    must be done client-side. Without it, a caller deleting the returned users
    would empty auth.users — including rows FK-locked by the open test
    transaction (DELETE blocked, 504 from Kong after 10s).
    """
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
    get_admin_supabase().auth.admin.delete_user(uid)
