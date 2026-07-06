"""Files-specific storage helpers; the Storage clients themselves live in
apps/shared/persistence/storage (promoted when avatars became the second consumer)."""

import uuid
from urllib.parse import urlparse, urlunparse

from apps.shared.config import get_technical_settings


def rewrite_signed_url(signed_url: str) -> str:
    """Replace the origin of a signed URL with the configured public storage URL."""
    s = get_technical_settings()
    parsed = urlparse(signed_url)
    target = urlparse(s.supabase_storage_url)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
