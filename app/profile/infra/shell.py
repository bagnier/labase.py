"""Shell composition: the cross-cutting context every authenticated HTML page needs.

A page is composed of fragments owned by apps. The "shell" (sidebar nav + the
current user's display name) is itself a provider: a single function doing a
single DB query. Routes call it explicitly via :func:`page_context` /
:func:`shell_context` instead of relying on hidden global dependencies.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.organizations.domain.models import Membership, Organization, OrgRole
from app.profile.domain.models import Profile

log = structlog.get_logger("labase.profile.shell")


@dataclass
class NavOrg:
    id: uuid.UUID
    name: str
    slug: str
    is_owner: bool


async def shell_context(session: AsyncSession, user: AuthenticatedUser | None) -> dict:
    """Display name + organisations of ``user`` in a single query.

    Relies on Postgres RLS (the request session already carries the user's
    context): the ``organizations: member read`` policy returns exactly the
    user's orgs, and ``profiles: own read`` exposes the display name.
    """
    if user is None:
        return {"display_name": None, "nav_orgs": []}
    user_id = uuid.UUID(user.id)
    display_name = (
        select(Profile.display_name).where(Profile.auth_user_id == user_id).scalar_subquery()
    )
    try:
        rows = (
            await session.execute(
                select(Organization, Membership.role, display_name)
                .join(Membership, Membership.org_id == Organization.id)
                .where(Membership.auth_user_id == user_id)
                .order_by(Organization.created_at)
            )
        ).all()
    except Exception:
        log.warning("profile.shell_load_failed")
        return {"display_name": None, "nav_orgs": []}
    return {
        "display_name": rows[0][2] if rows else None,
        "nav_orgs": [
            NavOrg(
                id=row[0].id,
                name=row[0].name,
                slug=row[0].slug,
                is_owner=row[1] == OrgRole.owner,
            )
            for row in rows
        ],
    }


async def page_context(
    session: AsyncSession, user: AuthenticatedUser | None, **extra: object
) -> dict:
    """Full template context for an authenticated page: shell + user + page extras."""
    return {"user": user, **await shell_context(session, user), **extra}
