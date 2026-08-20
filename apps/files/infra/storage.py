"""Files-specific storage helpers; the Storage clients themselves live in
apps/shared/persistence/storage (promoted when avatars became the second consumer)."""

import uuid
from urllib.parse import urlparse, urlunparse

from storage3.types import SignedUrlResponse

from apps.shared.settings.env import get_technical_settings


def rewrite_signed_url(signed_url: str) -> str:
    """Replace the origin of a signed URL with the configured public storage URL."""
    s = get_technical_settings()
    parsed = urlparse(signed_url)
    target = urlparse(s.supabase_storage_url)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def signed_redirect_url(result: SignedUrlResponse) -> str:
    """The origin-rewritten signed URL from a Storage ``create_signed_url`` response,
    tolerating both the ``signedURL`` and ``signedUrl`` spellings the SDK has used."""
    return rewrite_signed_url(result.get("signedURL") or result.get("signedUrl") or "")


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
