from collections.abc import AsyncGenerator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.infra.security import try_get_current_user
from apps.shared.persistence.database import get_user_session
from apps.shared.persistence.rls import set_rls_context


async def get_rls_session(
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
    session: AsyncSession = Depends(get_user_session),
) -> AsyncGenerator[AsyncSession]:
    """The single authenticated DB session for a request.

    The RLS context (role + JWT claims) is set **once** here; FastAPI caches the
    dependency, so every consumer in the request (fullpage provider, route, sub-deps)
    shares this same session and its single set-config round-trip. The context is
    transaction-local, so the request's commit/rollback clears it — no reset needed.
    Tolerant to anonymous callers — authentication (401) is enforced separately by
    ``CurrentUser`` where a route requires it.

    This session used to be *also* bound as an ambient unit of work, which ``emit`` read
    when no session was passed. That made a fact's durability depend on whether its route
    happened to depend on this function, so it is gone: ``emit`` now takes its session.
    """
    if current_user is not None:
        await set_rls_context(session, current_user.claims)
    yield session
