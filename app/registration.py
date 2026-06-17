import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import RegisterResult, register
from app.auth.infra.security import decode_jwt
from app.organizations.infra.repository import OrganizationRepository
from app.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger("labase.registration")


async def register_user(
    email: str, password: str, session: AsyncSession
) -> tuple[RegisterResult, uuid.UUID | None]:
    """Create Supabase auth user and, if no email confirmation is required, the personal org.

    Returns (result, org_id). org_id is None when email confirmation is pending —
    the org will be created at the confirmation callback instead.
    """
    result = await register(email, password)
    if result.access_token is None:
        return result, None
    try:
        org = await OrganizationRepository(session).create_with_owner(
            name=email,
            auth_user_id=uuid.UUID(result.user_id),
        )
    except Exception:
        log.warning("registration.org_creation_failed_compensating", user_id=result.user_id)
        supabase = get_admin_supabase()
        await asyncio.to_thread(supabase.auth.admin.delete_user, result.user_id)
        raise
    return result, org.id


async def confirm_user(access_token: str, session: AsyncSession) -> uuid.UUID:
    """Create the personal org for a user whose email was just confirmed.

    Returns org_id so the caller can emit the hook.
    """
    claims = decode_jwt(access_token)
    org = await OrganizationRepository(session).create_with_owner(
        name=claims.get("email", ""),
        auth_user_id=uuid.UUID(claims["sub"]),
    )
    return org.id
