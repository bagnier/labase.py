"""Admin-gated impersonation: mint a real GoTrue session for a target user.

``generate_link(magiclink)`` on the admin API returns the hashed token without
sending any mail; ``verify_otp`` exchanges it for the target's session. The
resulting JWT is genuine, so RLS and every downstream check behave exactly as
if the user had signed in themselves.
"""

import asyncio

from supabase_auth.errors import AuthError

from apps.auth.domain.service import AuthTokens, confirm_signup
from apps.shared.persistence.supabase import get_admin_supabase

# Where the admin's own session is stashed while impersonating: their presence is what renders the
# banner, and deleting them is what ends the disguise.
IMPERSONATOR_COOKIE = "impersonator_access_token"
IMPERSONATOR_REFRESH_COOKIE = "impersonator_refresh_token"

# The absolute unix deadline of the impersonation window, so a mid-window token refresh re-caps the
# re-emitted target session to the time it has left instead of the long login TTL.
IMPERSONATOR_DEADLINE_COOKIE = "impersonator_deadline"

# The time-box: every impersonation cookie dies after this long, disguise included.
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
