"""The API driver's isolation: every session runs on one connection, in a transaction rolled
back after each test. The browser driver truncates tables instead.
"""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import Session

from apps.shared.persistence.database import _user_session_factory
from apps.shared.persistence.rls import RLS_CLAIMS

_test_connection: AsyncConnection | None = None


def active_test_connection() -> AsyncConnection:
    """The scenario's connection; raises between scenarios."""
    if _test_connection is None:
        raise RuntimeError("No active test transaction")
    return _test_connection


async def begin_test_transaction(engine) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    # The app's FKs to auth.users are deferred to a commit that never comes: checked now, they
    # would hold a lock that a GoTrue write on its own connection would deadlock on.
    await conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    return conn


async def end_test_transaction(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()


def _speak_as_itself(session: Session) -> None:
    """Before each statement, apply this session's claims, or the login role: on the shared
    connection a role would leak between sessions, and a rolled-back savepoint undoes it."""
    connection = session.connection()
    claims = session.info.get(RLS_CLAIMS)
    if claims is None:
        connection.execute(text("RESET role"))
        connection.execute(text("RESET request.jwt.claims"))
    else:
        connection.execute(
            text(
                "SELECT set_config('role', 'app_rls', true), "
                "set_config('request.jwt.claims', :claims, true)"
            ),
            {"claims": claims},
        )


def session_on_test_connection() -> AsyncSession:
    session = AsyncSession(bind=active_test_connection(), expire_on_commit=False)
    event.listen(
        session.sync_session, "do_orm_execute", lambda state: _speak_as_itself(state.session)
    )
    event.listen(session.sync_session, "before_flush", lambda s, *_: _speak_as_itself(s))
    return session


async def seed_fixtures(fn):
    """Run ``fn(session)`` in the test transaction: seen by the app, discarded at teardown."""
    async with session_on_test_connection() as s:
        result = await fn(s)
        await s.commit()
        return result


async def override_get_session() -> AsyncGenerator[AsyncSession]:
    """Replaces the user and admin sessions: commits become savepoints on the test connection.
    ``get_rls_session`` runs unchanged on top."""
    if _test_connection is not None:
        async with session_on_test_connection() as session:
            yield session
            await session.commit()
    else:
        async with _user_session_factory()() as session:
            yield session
            await session.commit()
