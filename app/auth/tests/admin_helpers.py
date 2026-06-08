import httpx

from app.shared.config import get_settings


def admin_headers() -> dict:
    key = get_settings().supabase_service_role_key
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }


def create_user(email: str, password: str) -> str:
    r = httpx.post(
        f"{get_settings().supabase_url}/auth/v1/admin/users",
        headers=admin_headers(),
        json={"email": email, "password": password, "email_confirm": True},
    )
    r.raise_for_status()
    return r.json()["id"]


def delete_user(uid: str) -> None:
    r = httpx.delete(
        f"{get_settings().supabase_url}/auth/v1/admin/users/{uid}",
        headers=admin_headers(),
    )
    r.raise_for_status()
