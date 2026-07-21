"""Per-org cumulative completion counter — maintained by a durable async consumer of
``todo.ticked`` (see :func:`apps.todo.contract.integration._bump_completed`).

The counter is a server-owned aggregate: the consumer bumps it on the admin session (BYPASSRLS),
members only read their org's tally via RLS. It exists to demonstrate the outbox event fan-out —
an existing ``emit(TodoTicked)`` grew async behavior with no change to its producer.
"""

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def bump_completion(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Increment (or seed) the org's tally — called once per delivered ``todo.ticked``."""
    await session.execute(
        text(
            "INSERT INTO todo_completion_stats (org_id, completed) VALUES (CAST(:org AS uuid), 1) "
            "ON CONFLICT (org_id) DO UPDATE "
            "SET completed = todo_completion_stats.completed + 1, updated_at = now()"
        ),
        {"org": str(org_id)},
    )


async def completion_count(session: AsyncSession, org_id: uuid.UUID) -> int:
    """The org's cumulative completion count (0 before the first tick is delivered)."""
    value = await session.scalar(
        text("SELECT completed FROM todo_completion_stats WHERE org_id = CAST(:org AS uuid)"),
        {"org": str(org_id)},
    )
    return value or 0
