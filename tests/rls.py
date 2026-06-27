"""Shared primitives for direct (no-HTTP) RLS tests.

These run on the ``db_session`` fixture — a connection pinned to the
``authenticated`` Postgres role, where policies are actually enforced (the API
driver is BYPASSRLS and cannot exercise RLS). The pattern: seed rows as the
connection's bootstrap role, then switch identity with ``acting_as`` and assert
that policies hide other users' / orgs' rows.

Seeding stays feature-specific; only the identity switch and the visibility
assertion live here.
"""

from collections.abc import AsyncIterator, Iterable
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.shared.persistence.rls import clear_rls_context, set_rls_context


@asynccontextmanager
async def acting_as(session: AsyncSession, uid: str, **claims: Any) -> AsyncIterator[AsyncSession]:
    """Run the block as authenticated user ``uid`` — RLS policies see ``auth.uid()``.

    Restores the bootstrap role on exit, so the caller can seed further rows or
    switch to another identity on the same session. ``claims`` extends the JWT
    payload verbatim (e.g. ``role=`` or ``app_metadata=`` overrides).
    """
    await set_rls_context(session, {"sub": uid, "role": "authenticated", **claims})
    try:
        yield session
    finally:
        await clear_rls_context(session)


async def rows_visible_as(session: AsyncSession, uid: str, id_query: Select, **claims: Any) -> set:
    """Return the set of scalar values ``id_query`` yields for user ``uid``.

    ``id_query`` should select a single identifying column (e.g.
    ``select(Todo.id)``) so the result is a flat, comparable set of ids.
    """
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
    """Assert ``item`` is visible to ``visible_to`` and hidden from every other uid.

    ``id_query`` selects the identifying column; ``item`` is the id expected for
    the owner. Use to prove a single row is correctly scoped by RLS.
    """
    owner_sees = await rows_visible_as(session, visible_to, id_query, **claims)
    assert item in owner_sees, f"RLS hid {item!r} from its owner {visible_to!r}"
    for other in hidden_from:
        other_sees = await rows_visible_as(session, other, id_query, **claims)
        assert item not in other_sees, f"RLS leaked {item!r} to {other!r}"
