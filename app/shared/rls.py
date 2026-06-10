import json
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def bind_rls(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Set session-level role + JWT claims so Postgres RLS policies see auth.uid()."""
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})
    conn = await session.connection()
    await conn.execute(text("SET role authenticated"))
    await conn.execute(
        text("SELECT set_config('request.jwt.claims', :claims, false)").bindparams(claims=claims)
    )


async def reset_rls(session: AsyncSession) -> None:
    """Reset role and claims before the connection is returned to the pool."""
    conn = await session.connection()
    await conn.execute(text("RESET role"))
    await conn.execute(text("RESET request.jwt.claims"))
