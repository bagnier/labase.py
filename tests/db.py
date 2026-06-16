"""Shared test transaction state — one BYPASSRLS connection, automatic rollback."""

import contextlib
import json
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.shared.persistence.database import _user_session_factory, get_user_session

_test_connection: AsyncConnection | None = None


def in_test_transaction() -> bool:
    return _test_connection is not None


async def begin_test_transaction(engine) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    return conn


async def end_test_transaction(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()


@contextlib.asynccontextmanager
async def test_session() -> AsyncGenerator[AsyncSession]:
    """Session bound to the active test transaction connection."""
    assert _test_connection is not None, "No active test transaction"
    async with AsyncSession(bind=_test_connection, expire_on_commit=False) as s:
        yield s
        await s.commit()


async def override_get_session() -> AsyncGenerator[AsyncSession]:
    """Override for get_user_session and get_admin_session: session on the test connection.

    On a connection already in a transaction, SQLAlchemy emits SAVEPOINT/RELEASE
    instead of a real COMMIT. conn.rollback() at test end discards everything.
    """
    if _test_connection is not None:
        async with AsyncSession(bind=_test_connection, expire_on_commit=False) as session:
            yield session
            await session.commit()
    else:
        async with _user_session_factory()() as session:
            yield session
            await session.commit()


async def override_get_rls_session(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_user_session),
) -> AsyncGenerator[AsyncSession]:
    """Override for get_rls_session: sets request.jwt.claims so auth.uid() is
    available in SECURITY DEFINER functions, without SET role authenticated —
    the postgres user has BYPASSRLS. RLS tests stay in test_rls.py.
    """
    conn = await session.connection()
    claims = json.dumps({"sub": current_user.id, "role": "authenticated"})
    await conn.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)").bindparams(claims=claims)
    )
    yield session
