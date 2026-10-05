"""Supabase Studio deep links. The URL is browser-facing, so it cannot be derived from
``SUPABASE_API_URL``: ``SUPABASE_STUDIO_URL`` names it (``make env`` fills it), and empty hides the
link. A hosted project's dashboard follows from its ref, the fallback.
"""

from urllib.parse import urlparse

_CLOUD_SUFFIX = ".supabase.co"


def studio_base_url(studio_url: str, supabase_api_url: str) -> str | None:
    """The Studio base deep links are joined to, or ``None`` when this deployment has none."""
    if studio_url:
        return studio_url.rstrip("/")
    hostname = urlparse(supabase_api_url).hostname or ""
    if hostname.endswith(_CLOUD_SUFFIX):
        ref = hostname.removesuffix(_CLOUD_SUFFIX)
        return f"https://supabase.com/dashboard/project/{ref}"
    return None


def studio_link(studio_url: str, supabase_api_url: str, path: str) -> str | None:
    """Full Studio URL for a relative ``path`` fragment (e.g. ``auth/users``), or ``None``."""
    base = studio_base_url(studio_url, supabase_api_url)
    if base is None:
        return None
    return f"{base}/{path.lstrip('/')}"
