"""Row-Level Security context.

Postgres RLS is the **single source of truth** for data isolation: who can read
or write which rows is decided by the policies in supabase/migrations, evaluated
against the JWT claims set below. Do not reimplement isolation filters in Python —
the only app-level authorization check is the ``OwnerMembership`` /
``CurrentOwnerMembership`` gate, kept solely to return a clean 403 for owner-only
actions (RLS is the backstop).
"""

import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def set_rls_context(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Set session-level role + JWT claims so Postgres RLS policies see auth.uid()."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    conn = await session.connection()
    await conn.execute(text("SET role authenticated"))
    await conn.execute(
        text("SELECT set_config('request.jwt.claims', :claims, false)").bindparams(claims=claims)
    )


async def clear_rls_context(session: AsyncSession) -> None:
    """Reset role and claims before the connection is returned to the pool."""
    conn = await session.connection()
    await conn.execute(text("RESET role"))
    await conn.execute(text("RESET request.jwt.claims"))
