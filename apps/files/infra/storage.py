"""Files' Storage helpers; the clients are in apps/shared/persistence/storage."""

import uuid
from urllib.parse import urlparse, urlunparse

from storage3.types import SignedUrlResponse

from apps.shared.settings.env import get_technical_settings


def rewrite_signed_url(signed_url: str) -> str:
    """A signed URL with the public storage origin."""
    s = get_technical_settings()
    parsed = urlparse(signed_url)
    target = urlparse(s.supabase_storage_url)
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


def signed_redirect_url(result: SignedUrlResponse) -> str:
    """The rewritten signed URL from a ``create_signed_url`` response, under either spelling the
    SDK uses (``signedURL``, ``signedUrl``)."""
    return rewrite_signed_url(result.get("signedURL") or result.get("signedUrl") or "")


def storage_path(org_id: uuid.UUID, file_id: uuid.UUID, filename: str) -> str:
    return f"{org_id}/{file_id}_{filename}"
