"""Auth's public FastAPI dependencies — who is calling, and their DB session.

The aliases below are the sanctioned inter-context surface for authentication:
other contexts depend on ``CurrentUser`` / ``OptionalCurrentUser`` / ``RlsSession``
without reaching into ``auth/infra``. The real work lives in the providers they
wrap (``get_current_user`` decodes the JWT cookie and refreshes when expired;
``get_rls_session`` opens the request's RLS-scoped session).
"""

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
