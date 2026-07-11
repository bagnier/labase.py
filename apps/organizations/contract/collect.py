"""One grammar for the org collect slices.

Three org channels share one query shape — a session plus the org, optionally the
caller's role: :class:`~apps.organizations.contract.overviews.OverviewQuery`
(dashboard cards), :class:`~apps.organizations.contract.fullpage.OrgNavQuery`
(sidebar items) and
:class:`~apps.organizations.contract.settings_sections.OrgSettingsSectionQuery`
(settings sections). The console's server-wide ``ConsoleOverviewQuery`` is the same
grammar minus the org dimension. The bus dispatches on the *exact* type, so each
channel stays its own collection; these bases pin the shape (and this doc) in one
place instead of four.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class OrgQuery:
    """An org-scoped collect query: answered by every subscribed app for one org."""

    session: AsyncSession
    org_id: uuid.UUID


@dataclass(frozen=True)
class OrgMemberQuery(OrgQuery):
    """An org-scoped collect query asked on behalf of a member — carries their role."""

    is_owner: bool
