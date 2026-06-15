"""Test transaction helpers — shared connection + automatic rollback."""

import asyncio
import json
import threading
import uuid
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.organizations.domain.models import Membership, Organization
from app.shared.config import get_settings
from app.shared.persistence.database import _user_session_factory, get_user_session


def _service_engine():
    """Fresh NullPool engine on the service (BYPASSRLS) connection — for browser-side
    test helpers that commit to the real DB outside any test transaction."""
    settings = get_settings()
    url = settings.database_url_service or settings.database_url
    connect_args = {"server_settings": {"search_path": f"{settings.db_schema},public"}}
    return create_async_engine(url, poolclass=NullPool, connect_args=connect_args)


def _run_blocking[T](coro_factory: Callable[[], Awaitable[T]]) -> T:
    """Runs an async DB helper on a dedicated thread/loop, avoiding conflicts with the
    pytest-asyncio event loop. Mirrors truncate_app_tables()."""
    result: list[T] = []
    errors: list[Exception] = []

    def _target() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result.append(loop.run_until_complete(coro_factory()))
        except Exception as e:  # noqa: BLE001 — re-raised on the calling thread below
            errors.append(e)
        finally:
            loop.close()

    t = threading.Thread(target=_target, daemon=True)
    t.start()
    t.join()
    if errors:
        raise errors[0]
    return result[0]


def primary_org_for_user(user_id: str) -> dict:
    """First org (id/name/handle) the user belongs to, read through SQLAlchemy.

    Lets the browser driver resolve org identifiers for test setup without calling the
    JSON API — it drives the app through the DOM, not through REST.
    """

    async def _query() -> dict:
        engine = _service_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                org = await session.scalar(
                    select(Organization)
                    .join(Membership, Membership.org_id == Organization.id)
                    .where(Membership.auth_user_id == uuid.UUID(user_id))
                    .order_by(Membership.created_at)
                    .limit(1)
                )
                assert org is not None, f"User {user_id!r} has no organization"
                return {"id": str(org.id), "name": org.name, "handle": org.handle}
        finally:
            await engine.dispose()

    return _run_blocking(_query)


def orgs_for_user(user_id: str) -> list[dict]:
    """All orgs (id/name/handle/role) the user belongs to, read through SQLAlchemy.

    Browser-driver stand-in for ``GET /organizations``: the driver resolves multi-org
    state from the DB, never from the JSON API.
    """

    async def _query() -> list[dict]:
        engine = _service_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                rows = (
                    await session.execute(
                        select(Organization, Membership.role)
                        .join(Membership, Membership.org_id == Organization.id)
                        .where(Membership.auth_user_id == uuid.UUID(user_id))
                        .order_by(Membership.created_at)
                    )
                ).all()
                return [
                    {"id": str(org.id), "name": org.name, "handle": org.handle, "role": role.value}
                    for org, role in rows
                ]
        finally:
            await engine.dispose()

    return _run_blocking(_query)


def rename_org(org_id: str, name: str) -> None:
    """Renames an org through SQLAlchemy (browser-side test setup)."""

    async def _update() -> None:
        engine = _service_engine()
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                org = await session.get(Organization, uuid.UUID(org_id))
                assert org is not None, f"Org {org_id!r} not found"
                org.name = name
                await session.commit()
        finally:
            await engine.dispose()

    _run_blocking(_update)


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
