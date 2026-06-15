"""Test transaction helpers — shared connection + automatic rollback."""

import asyncio
import json
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.shared.config import get_settings
from app.shared.persistence.database import _user_session_factory, get_user_session

# Simple global (sequential tests): visible from all threads, including
# the driver event loop thread that runs FastAPI dependency overrides.
_test_connection: AsyncConnection | None = None

# Email domains reserved for test fixtures — scope of purge_leftover_test_data().
_TEST_EMAIL_DOMAINS = ["test.local", "example.com", "rls.local", "labase.dev"]


def in_test_transaction() -> bool:
    return _test_connection is not None


async def begin_test_transaction(engine) -> AsyncConnection:
    conn = await engine.connect()
    await conn.begin()
    return conn


async def end_test_transaction(conn: AsyncConnection) -> None:
    await conn.rollback()
    await conn.close()


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


async def fetch_orgs_for_email(email: str) -> list[dict]:
    """Query organisations+role for email via the test transaction connection.

    Used when the user is not authenticated (e.g. right after register()).
    """
    assert _test_connection is not None, "No active test transaction"
    result = await _test_connection.execute(
        text("""
            SELECT o.name, o.handle, o.id::text AS id, m.role
            FROM organizations o
            JOIN memberships m ON m.org_id = o.id
            JOIN profiles p ON p.auth_user_id = m.auth_user_id
            WHERE p.email = :email
        """),
        {"email": email},
    )
    return [dict(row._mapping) for row in result]


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


def truncate_app_tables() -> None:
    """Truncates all application tables — used in browser test teardown.

    Creates a fresh NullPool engine (like purge_leftover_test_data) and runs it
    in a dedicated thread to avoid conflicts with the pytest-asyncio event loop.
    """
    import threading

    errors: list[Exception] = []

    async def _truncate() -> None:
        settings = get_settings()
        url = settings.database_url_service or settings.database_url
        connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
        engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    text(
                        "TRUNCATE TABLE public.audit_logs, public.org_file_share_tokens, "
                        "public.org_files, public.todos, "
                        "public.card_states, public.deck_subscriptions, public.cards, "
                        "public.decks, public.org_invitations, "
                        "public.memberships, public.organizations, public.profiles CASCADE"
                    )
                )
                await conn.execute(
                    text("DELETE FROM auth.users WHERE split_part(email, '@', 2) = ANY(:domains)"),
                    {"domains": _TEST_EMAIL_DOMAINS},
                )
        finally:
            await engine.dispose()

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_truncate())
        except Exception as e:
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]


async def purge_leftover_test_data() -> None:
    """Deletes test data that survives teardowns.

    The browser driver does no cleanup, and a crashed run leaves residues:
    users from test domains (cascading memberships/profiles/todos/files),
    then orgs with no remaining membership.
    """
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    engine = create_async_engine(url, poolclass=NullPool, connect_args=connect_args)
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM auth.users WHERE split_part(email, '@', 2) = ANY(:domains)"),
                {"domains": _TEST_EMAIL_DOMAINS},
            )
            await conn.execute(
                text("""
                    DELETE FROM organizations o
                    WHERE NOT EXISTS (SELECT 1 FROM memberships m WHERE m.org_id = o.id)
                """)
            )
    finally:
        await engine.dispose()
