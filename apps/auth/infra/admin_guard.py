"""A transaction-scoped lock around the last-admin guard's count-then-act, taken by every path
that changes who is admin: console grant and revoke, account disable and delete, self-deletion.
Without it, two concurrent callers could both read the same count and both pass
``ensure_not_last_admin``.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# An arbitrary advisory-lock key; must differ from any other in the codebase (none so far).
_LAST_ADMIN_GUARD_LOCK_KEY = 3_600_360_036


async def lock_last_admin_guard(session: AsyncSession) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(:key)"), {"key": _LAST_ADMIN_GUARD_LOCK_KEY}
    )
