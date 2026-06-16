import uuid
from urllib.parse import urlparse, urlunparse

from storage3 import AsyncStorageClient

from app.shared.config import get_settings

BUCKET = "org-files"


def user_storage_client(access_token: str) -> AsyncStorageClient:
    s = get_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_storage_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": s.supabase_anon_key,
        },
    )


def service_storage_client() -> AsyncStorageClient:
    """Used only inside app boundary (e.g. public share proxy). Never expose to client."""
    s = get_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_storage_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {s.supabase_service_role_key}",
            "apikey": s.supabase_service_role_key,
        },
    )


def rewrite_signed_url(signed_url: str) -> str:
    """Replace the origin of a signed URL with the configured public storage URL."""
    s = get_settings()
    parsed = urlparse(signed_url)
    target = urlparse(s.supabase_storage_url)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
