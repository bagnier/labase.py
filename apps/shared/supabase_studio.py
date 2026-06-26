"""Derive Supabase Studio deep links from ``SUPABASE_API_URL``.

The console surfaces "open in Supabase" links for advanced management. There is no dedicated
config for the Studio URL, so it is inferred from the project's ``SUPABASE_API_URL``:

- a hosted project ``https://<ref>.supabase.co`` → ``https://supabase.com/dashboard/project/<ref>``
- anything else (local ``supabase start``) → the local Studio at ``localhost:54323``
"""

from urllib.parse import urlparse

_CLOUD_SUFFIX = ".supabase.co"
_LOCAL_STUDIO = "http://localhost:54323/project/default"


def studio_base_url(supabase_api_url: str) -> str:
    """Map a ``SUPABASE_API_URL`` to its Studio base URL (no trailing slash)."""
    hostname = urlparse(supabase_api_url).hostname or ""
    if hostname.endswith(_CLOUD_SUFFIX):
        ref = hostname.removesuffix(_CLOUD_SUFFIX)
        return f"https://supabase.com/dashboard/project/{ref}"
    return _LOCAL_STUDIO


def studio_link(supabase_api_url: str, path: str) -> str:
    """Full Studio URL for a relative ``path`` fragment (e.g. ``auth/users``)."""
    return f"{studio_base_url(supabase_api_url)}/{path.lstrip('/')}"
