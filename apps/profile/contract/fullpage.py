"""Profile's fullpage-context slice: the current user's handle.

Registered as a fullpage provider at profile's ``mount()`` and collected by
:func:`apps.shared.page.fullpage_context`. The page-assembly mechanism itself lives in
:mod:`apps.shared.page` — no global render hook injects data silently (a Jinja
"context processor" or middleware would, proscribed by the *Page composition* principle).
"""

import uuid

import structlog
from sqlalchemy import select

from apps.profile.domain.models import Profile
from apps.shared.page import FullpageQuery

log = structlog.get_logger("labase.profile.fullpage")


async def provide_profile_handle(query: FullpageQuery) -> dict:
    """Fullpage slice ``profile_handle``: the user's handle (RLS ``profiles: own read``)."""
    if query.user is None:
        return {"handle": None}
    try:
        handle = await query.session.scalar(
            select(Profile.handle).where(Profile.auth_user_id == uuid.UUID(query.user.id))
        )
    except Exception:
        log.exception("profile.fullpage_load_failed")
        return {"handle": None}
    return {"handle": handle}
