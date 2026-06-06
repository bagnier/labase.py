from dataclasses import dataclass

from app.shared.supabase_client import get_supabase


@dataclass
class AuthTokens:
    access_token: str
    refresh_token: str


def login(email: str, password: str) -> AuthTokens:
    auth = get_supabase().auth.sign_in_with_password({"email": email, "password": password})
    if auth.session is None:
        raise ValueError("No session returned")
    return AuthTokens(
        access_token=auth.session.access_token,
        refresh_token=auth.session.refresh_token,
    )


def logout() -> None:
    try:
        get_supabase().auth.sign_out()
    except Exception:
        pass


def register(email: str, password: str) -> None:
    get_supabase().auth.sign_up({"email": email, "password": password})
