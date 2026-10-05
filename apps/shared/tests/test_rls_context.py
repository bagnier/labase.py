"""The RLS context dies with its transaction: the pooled connection's next user, possibly
anonymous, never inherits the previous identity."""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.shared.persistence.rls import set_rls_context
from apps.shared.settings.env import get_technical_settings

_UID = "00000000-0000-0000-0000-000000000009"


@pytest_asyncio.fixture()
async def single_conn_engine():
    """A throwaway user engine with one pooled connection, so two sessions share a backend."""
    settings = get_technical_settings()
    connect_args = {
        "server_settings": {"search_path": f"{settings.supabase_database_schema},public"}
    }
    engine = create_async_engine(
        settings.supabase_database_user_url,
        connect_args=connect_args,
        pool_size=1,
        max_overflow=0,
    )
    try:
        yield engine
    finally:
        await engine.dispose()


async def _identity(session: AsyncSession) -> tuple[int, str, str | None]:
    row = (
        await session.execute(
            text(
                "SELECT pg_backend_pid(), current_user, current_setting('request.jwt.claims', true)"
            )
        )
    ).one()
    return row[0], row[1], row[2]


@pytest.mark.asyncio
async def test_rls_context_does_not_leak_across_pooled_reuse(single_conn_engine):
    async with AsyncSession(single_conn_engine, expire_on_commit=False) as a:
        await set_rls_context(a, {"sub": _UID, "role": "authenticated"})
        pid_a, role_a, claims_a = await _identity(a)
        assert role_a == "app_rls", "set_rls_context should switch the role"
        assert claims_a, "set_rls_context should set the JWT claims"
        assert _UID in claims_a, "set_rls_context should set the JWT claims"
        await a.commit()

    async with AsyncSession(single_conn_engine, expire_on_commit=False) as b:
        pid_b, role_b, claims_b = await _identity(b)
        await b.rollback()

    assert pid_a == pid_b, "test is only meaningful if the same backend is reused"
    assert role_b != "app_rls", "role leaked onto the reused connection"
    assert not claims_b, "jwt claims leaked onto the reused connection"
