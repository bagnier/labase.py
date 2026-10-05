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
    """The request's RLS session; FastAPI caches it, so the context is set once per request.
    Anonymous callers get one too; ``CurrentUser`` is what demands a sign-in."""
    # An anonymous caller gets claims naming nobody: on the bare login role every query fails.
    claims = current_user.claims if current_user is not None else {"role": "anon"}
    await set_rls_context(session, claims)
    yield session
