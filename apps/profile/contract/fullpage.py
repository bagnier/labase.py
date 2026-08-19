"""Profile's fullpage-context slice: the current user's handle.

Registered as a fullpage provider at profile's ``mount()`` and collected by
:func:`apps.shared.page.fullpage_context`. The page-assembly mechanism itself lives in
:mod:`apps.shared.page` — no global render hook injects data silently (a Jinja
"context processor" or middleware would, proscribed by the *Page composition* principle).
"""

import structlog
from sqlalchemy import select

from apps.profile.domain.models import Profile
from apps.shared.page import FullpageQuery
from apps.shared.settings import get_settings

log = structlog.get_logger(__name__)


async def provide_profile_handle(query: FullpageQuery) -> dict:
    """Fullpage slice ``profile_handle`` / ``profile_avatar_path``: the user's handle and
    avatar (RLS ``profiles: own read``). ``avatar_path`` stays ``None`` when the feature is
    off, so the nav footer falls back to the initial without re-reading the switch."""
    if query.user is None:
        return {"handle": None, "avatar_path": None}
    try:
        row = (
            await query.session.execute(
                select(Profile.handle, Profile.avatar_path).where(Profile.user_id == query.user.id)
            )
        ).first()
    except Exception:
        log.exception("profile.fullpage_load_failed")
        return {"handle": None, "avatar_path": None}
    handle = row.handle if row else None
    avatar_path = row.avatar_path if row else None
    if not get_settings("profile").view().avatar_enabled:
        avatar_path = None
    return {"handle": handle, "avatar_path": avatar_path}
