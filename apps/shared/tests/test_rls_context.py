"""The RLS context is transaction-local and must not survive connection reuse.

``set_rls_context`` sets the role + JWT claims with ``is_local=true``; the request path
relies on its single commit/rollback to discard them, issuing **no** reset round-trips
(see ``apps.auth.infra.session.get_rls_session``). This pins the invariant that makes that
safe: after a committed transaction, the same pooled backend carries neither the role nor
the claims onto its next borrower — otherwise an anonymous request could inherit the
previous authenticated request's identity.
"""

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from apps.shared.persistence.rls import set_rls_context
from apps.shared.settings.env import get_technical_settings

_UID = "00000000-0000-0000-0000-000000000009"


@pytest_asyncio.fixture()
async def single_conn_engine():
    """Real user engine pinned to one pooled connection (``pool_size=1``, no overflow).

    Two sequential sessions therefore provably reuse the same backend — the exact
    request → pool → request shape this test guards. A throwaway engine (not the cached
    one) keeps its pool bound to the test's event loop.
    """
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
    """(backend pid, current role, jwt claims) as this session's connection sees them."""
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
    """Session A: adopt an authenticated identity, then commit — which discards the transaction-
    local role + claims and returns the connection to the pool."""
    async with AsyncSession(single_conn_engine, expire_on_commit=False) as a:
        await set_rls_context(a, {"sub": _UID, "role": "authenticated"})
        pid_a, role_a, claims_a = await _identity(a)
        assert role_a == "authenticated", "set_rls_context should switch the role"
        assert claims_a, "set_rls_context should set the JWT claims"
        assert _UID in claims_a, "set_rls_context should set the JWT claims"
        await a.commit()

    # Session B: same single pooled connection, no context set of its own.
    async with AsyncSession(single_conn_engine, expire_on_commit=False) as b:
        pid_b, role_b, claims_b = await _identity(b)
        await b.rollback()

    assert pid_a == pid_b, "test is only meaningful if the same backend is reused"
    assert role_b != "authenticated", "role leaked onto the reused connection"
    assert not claims_b, "jwt claims leaked onto the reused connection"
