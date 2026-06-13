"""Helpers admin GoTrue pour les tests, via le client supabase service-role."""

from supabase_auth.types import User

from app.shared.persistence.supabase import get_admin_supabase


def find_users(email: str) -> list[User]:
    """Liste les users GoTrue ayant exactement cet email.

    L'API admin ne filtre pas par email et renvoie tous les users : le filtrage
    doit se faire côté client. Sans lui, un appelant qui supprime les users
    renvoyés vide auth.users — y compris des lignes FK-lockées par la
    transaction de test ouverte (DELETE bloqué, 504 Kong après 10s).
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
