import uuid

import structlog
from fastapi import Depends, Request
from sqlalchemy import select

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import try_get_current_user
from app.organizations.infra.repository import OrganizationRepository
from app.profile.domain.models import Profile
from app.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.profile.cache")

_cache: dict[uuid.UUID, str | None] = {}


def invalidate_display_name(user_id: uuid.UUID) -> None:
    _cache.pop(user_id, None)


async def load_display_name(
    request: Request,
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
) -> None:
    request.state.display_name = None
    if current_user is None:
        return
    try:
        user_id = uuid.UUID(current_user.id)
        if user_id not in _cache:
            async with admin_session_factory()() as session:
                _cache[user_id] = await session.scalar(
                    select(Profile.display_name).where(Profile.auth_user_id == user_id)
                )
        request.state.display_name = _cache[user_id]
    except Exception:
        log.warning("profile.display_name_load_failed")


async def load_nav_orgs(
    request: Request,
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
) -> None:
    request.state.nav_orgs = []
    if current_user is None:
        return
    try:
        async with admin_session_factory()() as session:
            pairs = await OrganizationRepository(session).list_with_role_for_user(
                uuid.UUID(current_user.id)
            )
            request.state.nav_orgs = [org for org, _ in pairs]
    except Exception:
        log.warning("profile.nav_orgs_load_failed")


def profile_context(request: Request) -> dict:
    return {
        "display_name": getattr(request.state, "display_name", None),
        "nav_orgs": getattr(request.state, "nav_orgs", []),
    }
