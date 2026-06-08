import uuid
from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.shared.database import get_session
from app.shared.rls import bind_rls, reset_rls


async def get_rls_session(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[AsyncSession, None]:
    """Session utilisateur avec rôle + claims RLS injectés pour toute la durée de la requête."""
    await bind_rls(session, uuid.UUID(current_user.id))
    try:
        yield session
    finally:
        try:
            await reset_rls(session)
        except Exception:
            pass
