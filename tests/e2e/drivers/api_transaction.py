"""Transactional isolation for the **API driver** — not used by the browser driver.

One connection wrapped in a transaction that is rolled back after each
test: every FastAPI session is overridden onto it (see ApiBase.setup_test), so the
whole test is discarded with a single rollback instead of per-table cleanup. The
browser driver, which talks to a real server subprocess, uses table truncation
instead (see browser_base / tests.cleanup).
"""

from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession
from sqlalchemy.orm import Session

from apps.shared.persistence.database import _user_session_factory
from apps.shared.persistence.rls import RLS_CLAIMS

_test_connection: AsyncConnection | None = None


def active_test_connection() -> AsyncConnection:
    """The scenario's rolled-back connection. Between scenarios there is none, which is why the
    global stays ``| None`` — and why readers go through here, where that is said once."""
    if _test_connection is None:
        raise RuntimeError("No active test transaction")
    return _test_connection


async def begin_test_transaction(engine) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    # This transaction wraps a whole scenario and is rolled back, never committed. An app→auth.users
    # FK would otherwise hold a FOR KEY SHARE lock on the referenced auth.users row for the whole
    # test; a later GoTrue mutation of that user (sign-in, delete) — on its own connection — would
    # then block on this never-committing transaction and self-deadlock. Deferring the deferrable
    # constraints (the app→auth.users FKs, see 20260723000001) moves their check to a commit that
    # never runs, so no lock is taken. App-internal FKs stay NOT DEFERRABLE, checked immediately.
    await conn.execute(text("SET CONSTRAINTS ALL DEFERRED"))
    return conn


async def end_test_transaction(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()


def _speak_as_itself(session: Session) -> None:
    """Say who this session is before it talks: the claims it last set, or the login role.

    Every session a request opens shares the one test connection, where production gives each its
    own — so a role set by the RLS session would otherwise carry over to the admin session's next
    statement, and a reset by the admin session would strip the RLS one. Transaction-local, like
    the real setting, and re-applied every time: a rolled-back savepoint undoes it silently."""
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
    """A session on the scenario's connection that keeps its own identity there."""
    session = AsyncSession(bind=active_test_connection(), expire_on_commit=False)
    event.listen(
        session.sync_session, "do_orm_execute", lambda state: _speak_as_itself(state.session)
    )
    event.listen(session.sync_session, "before_flush", lambda s, *_: _speak_as_itself(s))
    return session


async def seed_fixtures(fn):
    """Run ``fn(session)`` on the active test transaction and commit.

    Lets tests inject fixtures straight onto the rolled-back transaction (no HTTP),
    so the writes are visible to the app and discarded at teardown — without callers
    reaching into _test_connection. API-driver only (browser mode has no transaction).
    """
    async with session_on_test_connection() as s:
        result = await fn(s)
        await s.commit()
        return result


async def override_get_session() -> AsyncGenerator[AsyncSession]:
    """Override for get_user_session and get_admin_session: session on the test connection.

    On a connection already in a transaction, SQLAlchemy emits SAVEPOINT/RELEASE
    instead of a real COMMIT. conn.rollback() at test end discards everything. The real
    ``get_rls_session`` runs on top of it unchanged: it sets the role and claims, and the session
    carries them to each of its statements (see ``_speak_as_itself``).
    """
    if _test_connection is not None:
        async with session_on_test_connection() as session:
            yield session
            await session.commit()
    else:
        async with _user_session_factory()() as session:
            yield session
            await session.commit()
