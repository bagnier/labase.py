"""Transactional isolation for the **API driver** — not used by the browser driver.

One BYPASSRLS connection wrapped in a transaction that is rolled back after each
test: every FastAPI session is overridden onto it (see ApiBase.setup_test), so the
whole test is discarded with a single rollback instead of per-table cleanup. The
browser driver, which talks to a real server subprocess, uses table truncation
instead (see browser_base / tests.cleanup).
"""

import json
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from apps.auth.domain.service import AuthenticatedUser
from apps.auth.infra.security import try_get_current_user
from apps.shared.persistence.database import _user_session_factory, get_user_session
from apps.shared.persistence.uow import bind_current_session, reset_current_session

_test_connection: AsyncConnection | None = None


async def begin_test_transaction(engine) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    return conn


async def end_test_transaction(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()


async def seed_fixtures(fn):
    """Run ``fn(session)`` on the active test transaction and commit.

    Lets tests inject fixtures straight onto the rolled-back transaction (no HTTP),
    so the writes are visible to the app and discarded at teardown — without callers
    reaching into _test_connection. API-driver only (browser mode has no transaction).
    """
    assert _test_connection is not None, "No active test transaction"
    async with AsyncSession(bind=_test_connection, expire_on_commit=False) as s:
        result = await fn(s)
        await s.commit()
        return result


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
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
    session: AsyncSession = Depends(get_user_session),
) -> AsyncGenerator[AsyncSession]:
    """Override for get_rls_session: sets request.jwt.claims so auth.uid() is
    available in SECURITY DEFINER functions, without SET role authenticated —
    the postgres user has BYPASSRLS. RLS tests stay in test_rls.py. Tolerant to
    anonymous callers, mirroring get_rls_session's own contract.
    """
    if current_user is not None:
        conn = await session.connection()
        claims = json.dumps({"sub": current_user.id, "role": "authenticated"})
        await conn.execute(
            text("SELECT set_config('request.jwt.claims', :claims, true)").bindparams(claims=claims)
        )
    # Bind the ambient unit of work, exactly as the real get_rls_session does, so emit()'s durable
    # fan-out enqueues on this same (rolled-back) test transaction.
    token = bind_current_session(session)
    try:
        yield session
    finally:
        reset_current_session(token)
