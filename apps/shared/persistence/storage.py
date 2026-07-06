"""Supabase Storage clients — shared by every context that stores blobs.

Promoted from apps/files when profile avatars became the second consumer.
"""

from storage3 import AsyncStorageClient

from apps.shared.config import get_technical_settings


def bucket() -> str:
    """The Storage bucket name for the active env (per-worktree isolation aware)."""
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
    """Used only inside app boundary (share proxy, avatars). Never expose to client."""
    s = get_technical_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_api_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {s.supabase_secret_key}",
            "apikey": s.supabase_secret_key,
        },
    )
