"""The ``profile_*`` full-page slice: the user's handle and avatar."""

import structlog
from sqlalchemy import select

from apps.profile.domain.models import Profile
from apps.shared.integration.fullpage import FullpageQuery
from apps.shared.settings.live import get_settings

log = structlog.get_logger(__name__)


async def provide_profile_handle(query: FullpageQuery) -> dict:
    """``avatar_path`` is ``None`` when avatars are off, so the nav shows the initial."""
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
