"""Impersonation: a real GoTrue session for the target, minted from an unsent magic link, so RLS
and every check behave as if the user signed in.
"""

import asyncio

from supabase_auth.errors import AuthError

from apps.auth.domain.service import AuthTokens, confirm_signup
from apps.shared.persistence.supabase import get_admin_supabase

# The admin's stashed session: its presence shows the banner, its deletion ends the disguise.
IMPERSONATOR_COOKIE = "impersonator_access_token"
IMPERSONATOR_REFRESH_COOKIE = "impersonator_refresh_token"

# The window's unix deadline, so a refresh caps the target session to the time left.
IMPERSONATOR_DEADLINE_COOKIE = "impersonator_deadline"

IMPERSONATION_MAX_SECONDS = 3600


class ImpersonationTargetNotFound(Exception):
    """No auth user matches the requested email."""


async def impersonation_tokens(email: str) -> AuthTokens:
    supabase = get_admin_supabase()
    try:
        link = await asyncio.to_thread(
            supabase.auth.admin.generate_link, {"type": "magiclink", "email": email}
        )
    except AuthError as exc:
        raise ImpersonationTargetNotFound(email) from exc
    return await confirm_signup(link.properties.hashed_token, type="magiclink")
