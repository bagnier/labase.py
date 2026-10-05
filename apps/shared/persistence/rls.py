"""The RLS identity of a session (AGENTS: the database enforces isolation and authorization)."""

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# The claims a session speaks under. Read only by the API test lane, which runs every session on
# one connection and re-applies them before each statement.
RLS_CLAIMS = "rls_claims"


async def set_rls_context(session: AsyncSession, claims: Mapping[str, Any]) -> None:
    """Run the session as ``app_rls`` under ``claims``, the verified JWT payload, which policies
    read as is (``auth.uid()``, ``auth.jwt()``). The role is fixed, never taken from the token.

    Transaction-local: the request's single commit or rollback discards both, so nothing leaks to
    the pooled connection's next user.
    """
    conn = await session.connection()
    await conn.execute(
        text(
            "SELECT set_config('role', 'app_rls', true), "
            "set_config('request.jwt.claims', :claims, true)"
        ).bindparams(claims=json.dumps(claims))
    )
    session.info[RLS_CLAIMS] = json.dumps(claims)


async def clear_rls_context(session: AsyncSession) -> None:
    """Reset role and claims inside an open transaction, for a session that changes identity
    (the queue worker, ``tests/rls.py``). A request needs none."""
    conn = await session.connection()
    await conn.execute(text("RESET role"))
    await conn.execute(text("RESET request.jwt.claims"))
    session.info.pop(RLS_CLAIMS, None)
