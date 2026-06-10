import uuid

from storage3 import AsyncStorageClient

from app.shared.config import get_settings

BUCKET = "org-files"


def service_storage_client() -> AsyncStorageClient:
    s = get_settings()
    return AsyncStorageClient(
        url=f"{s.supabase_url}/storage/v1",
        headers={
            "Authorization": f"Bearer {s.supabase_service_role_key}",
            "apikey": s.supabase_service_role_key,
        },
    )


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
