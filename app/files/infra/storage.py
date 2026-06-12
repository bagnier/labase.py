import uuid

from storage3 import AsyncStorageClient

from app.shared.config import get_settings

BUCKET = "org-files"


def user_storage_client(access_token: str) -> AsyncStorageClient:
    s = get_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {access_token}",
            "apikey": s.supabase_anon_key,
        },
    )


def service_storage_client() -> AsyncStorageClient:
    """Used only inside app boundary (e.g. public share proxy). Never expose to client."""
    s = get_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_url}/storage/v1/",
        headers={
            "Authorization": f"Bearer {s.supabase_service_role_key}",
            "apikey": s.supabase_service_role_key,
        },
    )


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
