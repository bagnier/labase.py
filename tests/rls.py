"""For RLS tests on ``db_session``: seed as the bootstrap role, then switch identity with
``acting_as`` and check what the policies hide.
"""

import json
from collections.abc import AsyncGenerator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.persistence.rls import clear_rls_context, set_rls_context


@asynccontextmanager
async def acting_as(session: AsyncSession, uid: str, **claims: Any) -> AsyncGenerator[AsyncSession]:
    """Run the block as ``uid``, then back to the bootstrap role. ``claims`` extends the JWT."""
    await set_rls_context(session, {"sub": uid, "role": "authenticated", **claims})
    try:
        yield session
    finally:
        await clear_rls_context(session)


@asynccontextmanager
async def as_api_client(session: AsyncSession, uid: str) -> AsyncGenerator[AsyncSession]:
    """As PostgREST runs ``uid``'s request: the ``authenticated`` role, not the server's."""
    conn = await session.connection()
    await conn.execute(
        text(
            "SELECT set_config('role', 'authenticated', true), "
            "set_config('request.jwt.claims', :claims, true)"
        ).bindparams(claims=json.dumps({"sub": uid, "role": "authenticated"}))
    )
    try:
        yield session
    finally:
        await clear_rls_context(session)


async def rows_visible_as(session: AsyncSession, uid: str, id_query: Select, **claims: Any) -> set:
    """The ids ``id_query`` (one column, ``select(Todo.id)``) yields for ``uid``."""
    async with acting_as(session, uid, **claims):
        result = await session.execute(id_query)
        return set(result.scalars().all())


async def assert_rls_isolation(
    session: AsyncSession,
    id_query: Select,
    *,
    item: Any,
    visible_to: str,
    hidden_from: Iterable[str],
    **claims: Any,
) -> None:
    """``item`` is visible to ``visible_to`` only."""
    owner_sees = await rows_visible_as(session, visible_to, id_query, **claims)
    assert item in owner_sees, f"RLS hid {item!r} from its owner {visible_to!r}"
    for other in hidden_from:
        other_sees = await rows_visible_as(session, other, id_query, **claims)
        assert item not in other_sees, f"RLS leaked {item!r} to {other!r}"
