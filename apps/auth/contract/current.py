"""Auth's dependencies for other contexts: who is calling, and the request's RLS session."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.infra.security import get_current_admin, get_current_user, try_get_current_user
from apps.auth.infra.session import get_rls_session

CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
OptionalCurrentUser = Annotated[AuthenticatedUser | None, Depends(try_get_current_user)]
CurrentAdmin = Annotated[AuthenticatedUser, Depends(get_current_admin)]
RlsSession = Annotated[AsyncSession, Depends(get_rls_session)]
