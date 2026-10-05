"""The shared shape of the org contribution queries (dashboard cards, sidebar items, settings
sections): a session, the org, and maybe the caller's role. Each stays its own type, since contribs
dispatches on the exact type.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OrgQuery:
    session: AsyncSession
    org_id: uuid.UUID


@dataclass(frozen=True)
class OrgMemberQuery(OrgQuery):
    """Carries the asking member's role."""

    is_owner: bool
