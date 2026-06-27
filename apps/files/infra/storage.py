import uuid
from urllib.parse import urlparse, urlunparse

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
    """Used only inside app boundary (e.g. public share proxy). Never expose to client."""
    s = get_technical_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_api_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {s.supabase_secret_key}",
            "apikey": s.supabase_secret_key,
        },
    )


def rewrite_signed_url(signed_url: str) -> str:
    """Replace the origin of a signed URL with the configured public storage URL."""
    s = get_technical_settings()
    parsed = urlparse(signed_url)
    target = urlparse(s.supabase_storage_url)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
