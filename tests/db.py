"""Test transaction helpers — connexion partagée + rollback automatique."""

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

# Global simple (tests séquentiels) : visible depuis tous les threads, notamment
# celui de l'event loop du driver qui exécute les overrides FastAPI.
_test_connection: AsyncConnection | None = None

# Domaines réservés aux fixtures de test — périmètre de purge_leftover_test_data().
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


async def override_get_session() -> AsyncGenerator[AsyncSession, None]:
    """Override get_user_session et get_admin_session : session sur la connexion de test.

    Les repos appellent session.commit() eux-mêmes ; sur une connexion déjà en transaction,
    SQLAlchemy émet SAVEPOINT/RELEASE SAVEPOINT au lieu de COMMIT réel.
    Le conn.rollback() en fin de test annule tout.
    """
    if _test_connection is not None:
        async with AsyncSession(bind=_test_connection, expire_on_commit=False) as session:
            yield session
    else:
        async with _user_session_factory()() as session:
            yield session


async def fetch_orgs_for_email(email: str) -> list[dict]:
    """Query organisations+role for email via the test transaction connection.

    Utilisé quand le user n'est pas authentifié (ex: juste après register()).
    """
    assert _test_connection is not None, "No active test transaction"
    result = await _test_connection.execute(
        text("""
            SELECT o.name, o.slug, o.id::text AS id, m.role
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
) -> AsyncGenerator[AsyncSession, None]:
    """Override de get_rls_session : pose request.jwt.claims pour que auth.uid()
    soit disponible dans les fonctions SECURITY DEFINER, sans SET role authenticated —
    le user postgres a BYPASSRLS. Les tests RLS restent dans test_rls.py.
    """
    conn = await session.connection()
    claims = json.dumps({"sub": current_user.id, "role": "authenticated"})
    await conn.execute(
        text("SELECT set_config('request.jwt.claims', :claims, true)").bindparams(claims=claims)
    )
    yield session


async def purge_leftover_test_data() -> None:
    """Supprime les données de test qui survivent aux teardowns.

    Le driver browser ne nettoie rien, et un run crashé laisse des résidus :
    users des domaines de test (cascade memberships/profiles/todos/files),
    puis orgs sans plus aucune membership.
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
