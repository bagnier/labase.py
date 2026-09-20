"""Supabase Studio deep links, from configuration rather than guesswork.

The Studio URL is *browser-facing*: the admin's browser follows it, so nothing derived from the
server-side ``SUPABASE_API_URL`` (a docker host, a worktree's port) can stand in for it —
``SUPABASE_STUDIO_URL`` names it explicitly, and ``make env`` fills it from ``supabase status``.
Empty means what it says: this deployment has no Studio (the test stacks run without one), and
the console hides the link. The one derivable case is a hosted project, whose dashboard URL
follows from the project ref alone — for everyone, forever — so it stays the fallback.
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
