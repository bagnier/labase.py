import uuid
from collections.abc import AsyncGenerator

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.shared.persistence.database import get_user_session
from app.shared.persistence.rls import clear_rls_context, set_rls_context

log = structlog.get_logger("labase.auth.session")


async def get_rls_session(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_user_session),
) -> AsyncGenerator[AsyncSession]:
    """Session utilisateur avec rôle + claims RLS injectés pour toute la durée de la requête."""
    await set_rls_context(session, uuid.UUID(current_user.id))
    try:
        yield session
    finally:
        try:
            await clear_rls_context(session)
        except Exception:
            log.warning("rls.reset_failed", user_id=current_user.id)
