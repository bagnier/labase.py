import uuid

import jwt
import structlog
from fastapi import Request
from sqlalchemy import select

from app.auth.infra.security import decode_jwt
from app.profile.domain.models import Profile
from app.shared.persistence.database import admin_session_factory

log = structlog.get_logger("labase.profile.cache")

_cache: dict[uuid.UUID, str | None] = {}


def invalidate_display_name(user_id: uuid.UUID) -> None:
    _cache.pop(user_id, None)


async def load_display_name(request: Request) -> None:
    request.state.display_name = None
    token = request.cookies.get("access_token")
    if not token:
        return
    try:
        payload = decode_jwt(token)
        user_id = uuid.UUID(payload["sub"])
        if user_id not in _cache:
            async with admin_session_factory()() as session:
                _cache[user_id] = await session.scalar(
                    select(Profile.display_name).where(Profile.auth_user_id == user_id)
                )
        request.state.display_name = _cache[user_id]
    except jwt.PyJWTError:
        pass
    except Exception:
        log.warning("profile.display_name_load_failed")


def profile_context(request: Request) -> dict:
    return {"display_name": getattr(request.state, "display_name", None)}
