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
    """Set the role + JWT claims so Postgres RLS policies see auth.uid().

    ``claims`` is the verified JWT payload, passed through verbatim so policies can
    read any claim (auth.jwt(), auth.email(), app_metadata...). The Postgres role is
    pinned server-side to ``authenticated`` and never driven by the token's role claim.

    Both are set **transaction-local** (``set_config(..., is_local=true)``), in a single
    round-trip: ``session.connection()`` has opened the request's transaction, and the
    request commits/rolls back exactly once (see ``_commit_on_success``), at which point
    Postgres discards these settings automatically — so no reset round-trips are needed
    and nothing can leak onto the next borrower of the pooled connection.
    """
    conn = await session.connection()
    await conn.execute(
        text(
            "SELECT set_config('role', 'authenticated', true), "
            "set_config('request.jwt.claims', :claims, true)"
        ).bindparams(claims=json.dumps(claims))
    )


async def clear_rls_context(session: AsyncSession) -> None:
    """Reset role and claims mid-transaction, for callers that reuse one session.

    The HTTP request path does **not** need this — its single commit/rollback discards the
    transaction-local context set above. It stays for the two consumers that toggle identity
    on a still-open transaction: the queue worker (belt-and-suspenders around a task that owns
    its own commit) and the direct RLS tests (``tests/rls.py`` switches between users on one
    rolled-back session, so it must undo the previous identity explicitly)."""
    conn = await session.connection()
    await conn.execute(text("RESET role"))
    await conn.execute(text("RESET request.jwt.claims"))
