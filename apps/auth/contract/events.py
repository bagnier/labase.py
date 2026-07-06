"""Auth's public events — a user's identity begins and ends here.

The org context reacts to both (creating the personal org on ``UserCreated``,
cleaning memberships and orphaned orgs on ``UserDeleted``). Auth stays ignorant
of who listens. ``access_token`` is ``None`` when email confirmation is pending;
the org context skips seeding in that case and picks it up when the confirmation
callback fires.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class UserCreated:
    user_id: str
    email: str
    access_token: str | None


@dataclass(frozen=True)
class UserDeleted:
    """Emitted by the account-deletion flow, before the GoTrue soft delete.

    Carries the deleting request's (admin) session so handlers join its
    transaction — the deletion commits or rolls back as one unit.
    """

    user_id: str
    session: AsyncSession
