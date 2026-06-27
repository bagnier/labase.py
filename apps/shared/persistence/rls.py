"""Row-Level Security context.

Postgres RLS is the **single source of truth** for data isolation: who can read
or write which rows is decided by the policies in supabase/migrations, evaluated
against the JWT claims set below. Do not reimplement isolation filters in Python —
the only app-level authorization check is the ``OwnerMembership`` /
``CurrentOwnerMembership`` gate, kept solely to return a clean 403 for owner-only
actions (RLS is the backstop).
"""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(session: AsyncSession, claims: Mapping[str, Any]) -> None:
    """Set session-level role + JWT claims so Postgres RLS policies see auth.uid().

    ``claims`` is the verified JWT payload, passed through verbatim so policies can
    read any claim (auth.jwt(), auth.email(), app_metadata...). The Postgres role is
    pinned server-side to ``authenticated`` and never driven by the token's role claim.
    """
    conn = await session.connection()
    await conn.execute(text("SET role authenticated"))
    await conn.execute(
        text("SELECT set_config('request.jwt.claims', :claims, false)").bindparams(
            claims=json.dumps(claims)
        )
    )


async def clear_rls_context(session: AsyncSession) -> None:
    """Reset role and claims before the connection is returned to the pool."""
    conn = await session.connection()
    await conn.execute(text("RESET role"))
    await conn.execute(text("RESET request.jwt.claims"))
