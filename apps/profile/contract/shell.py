"""Profile's page-context slice: the current user's handle.

Registered as a page context provider at profile's ``mount()`` and collected by
:func:`apps.shared.page.shell_context`. The page-assembly mechanism itself lives in
:mod:`apps.shared.page` — no global render hook injects data silently (a Jinja
"context processor" or middleware would, proscribed by the *Page composition* principle).
"""

import uuid

import structlog
from sqlalchemy import select

from apps.profile.domain.models import Profile
from apps.shared.page import PageContextQuery

log = structlog.get_logger("labase.profile.shell")


async def provide_profile_handle(query: PageContextQuery) -> dict:
    """Page context slice ``profile_handle``: the user's handle (RLS ``profiles: own read``)."""
    if query.user is None:
        return {"profile_handle": None}
    try:
        handle = await query.session.scalar(
            select(Profile.handle).where(Profile.auth_user_id == uuid.UUID(query.user.id))
        )
    except Exception:
        log.exception("profile.shell_load_failed")
        return {"profile_handle": None}
    return {"profile_handle": handle}
