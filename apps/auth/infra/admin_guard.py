"""Serializes the last-admin guard's count-then-act against every caller that can make an
admin stop being one — a console revoke, the admin's own account deletion (apps/profile), and
an admin disabling or deleting another account from the console (apps/auth) — plus a console
grant, whose directory read-then-write is the same shape even though a promotion can only raise
the count.

Held for the caller's own transaction: a second concurrent caller blocks here until the first
commits, then re-reads a count that already reflects it — so two callers can no longer both
read the same stale count and both pass ``ensure_not_last_admin`` (issue #36).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# This invariant's own fixed identifier for the advisory lock — arbitrary, but must stay
# distinct from any other advisory lock key added anywhere in this codebase (there are none
# yet). Not derived from a name: hashing a string into the 64-bit space the single-argument
# `pg_advisory_xact_lock(bigint)` takes would trade one collision risk for another.
_LAST_ADMIN_GUARD_LOCK_KEY = 3_600_360_036


async def lock_last_admin_guard(session: AsyncSession) -> None:
    await session.execute(
        text("select pg_advisory_xact_lock(:key)"), {"key": _LAST_ADMIN_GUARD_LOCK_KEY}
    )
