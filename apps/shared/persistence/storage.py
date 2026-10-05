"""Supabase Storage clients, for every context that stores blobs."""

from storage3 import AsyncStorageClient

from apps.shared.settings.env import get_technical_settings


def bucket() -> str:
    return get_technical_settings().supabase_storage_bucket


def user_storage_client(access_token: str) -> AsyncStorageClient:
    s = get_technical_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_api_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": s.supabase_publishable_key,
        },
    )


def admin_storage() -> AsyncStorageClient:
    """Bypasses Storage policies: server-side only (share proxy, avatars), never sent out."""
    s = get_technical_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_api_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {s.supabase_secret_key}",
            "apikey": s.supabase_secret_key,
        },
    )
