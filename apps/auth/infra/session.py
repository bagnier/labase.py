from collections.abc import AsyncGenerator

import structlog
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.infra.security import try_get_current_user
from apps.shared.persistence.database import get_user_session
from apps.shared.persistence.rls import clear_rls_context, set_rls_context

log = structlog.get_logger("labase.auth.session")


async def get_rls_session(
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
    session: AsyncSession = Depends(get_user_session),
) -> AsyncGenerator[AsyncSession]:
    """The single authenticated DB session for a request.

    The RLS context (role + JWT claims) is set **once** here; FastAPI caches the
    dependency, so every consumer in the request (shell provider, route, sub-deps)
    shares this same session and the single ``SET role`` round-trip. Tolerant to
    anonymous callers — authentication (401) is enforced separately by
    ``CurrentUser`` where a route requires it.
    """
    if current_user is not None:
        await set_rls_context(session, current_user.claims)
    try:
        yield session
    finally:
        if current_user is not None:
            try:
                await clear_rls_context(session)
            except Exception:
                log.exception("rls.reset_failed", user_id=current_user.id)
