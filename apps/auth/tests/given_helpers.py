"""GoTrue helpers for test setup, via the supabase service-role client."""

from supabase_auth.types import User

from apps.shared.persistence.supabase import get_admin_supabase


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


def set_admin_role(uid: str) -> None:
    """Promote a user to server admin via the admin-only ``app_metadata.role`` claim.

    GoTrue embeds ``app_metadata`` in the access token, so the role lands in the JWT on the
    user's next sign-in. Must be called *before* sign-in for the token to carry it.
    """
    get_admin_supabase().auth.admin.update_user_by_id(uid, {"app_metadata": {"role": "admin"}})


def clear_all_admin_roles() -> None:
    """Strip the ``app_metadata.role`` claim from every GoTrue user.

    Bootstrap promotes the first user only when the server has *zero* admins. Admins linger in
    GoTrue across scenarios (the rollback/truncate isolation does not touch auth.users), so a
    bootstrap scenario must reset the count to zero first.
    """
    admin = get_admin_supabase().auth.admin
    page = 1
    while True:
        users = admin.list_users(page=page, per_page=1000)
        for u in users:
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
    """An account whose mailbox was never verified — only creatable via the admin
    API locally, where signup autoconfirm is on."""
    resp = get_admin_supabase().auth.admin.create_user(
        {"email": email, "password": password, "email_confirm": False}
    )
    assert resp.user, f"create_unconfirmed_user({email!r}) returned no user"
    return resp.user.id
