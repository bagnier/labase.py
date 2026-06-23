"""Shell composition: the cross-cutting context every authenticated HTML page needs.

A page is composed of fragments owned by apps. The "shell" (sidebar nav + the
current user's handle) is itself a provider: a single function doing a
single DB query. Routes call it explicitly via :func:`page_context` /
:func:`shell_context` instead of relying on hidden global dependencies.
"""

import uuid
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.current import AuthenticatedUser
from apps.organizations.contract.queries import get_user_orgs
from apps.profile.domain.models import Profile
from apps.shared.host import host

log = structlog.get_logger("labase.profile.shell")


@dataclass
class NavOrg:
    id: uuid.UUID
    name: str
    handle: str
    is_owner: bool


async def shell_context(session: AsyncSession, user: AuthenticatedUser | None) -> dict:
    """Handle + organisations of ``user`` in a single query.

    Relies on Postgres RLS (the request session already carries the user's
    context): the ``organizations: member read`` policy returns exactly the
    user's orgs, and ``profiles: own read`` exposes the handle.
    """
    nav_items = sorted(host.nav_items, key=lambda i: i.order)
    if user is None:
        return {"handle": None, "orgs": [], "nav_items": nav_items}
    user_id = uuid.UUID(user.id)
    try:
        handle = await session.scalar(select(Profile.handle).where(Profile.auth_user_id == user_id))
        orgs = await get_user_orgs(session, user_id)
    except Exception:
        log.warning("profile.shell_load_failed")
        return {"handle": None, "orgs": [], "nav_items": nav_items}
    return {
        "handle": handle,
        "orgs": [NavOrg(id=o.id, name=o.name, handle=o.handle, is_owner=o.is_owner) for o in orgs],
        "nav_items": nav_items,
    }


async def page_context(
    session: AsyncSession, user: AuthenticatedUser | None, **extra: object
) -> dict:
    """Full template context for an authenticated page: shell + user + page extras."""
    return {"user": user, **await shell_context(session, user), **extra}
