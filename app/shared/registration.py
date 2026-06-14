import asyncio
import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import register
from app.organizations.infra.repository import OrganizationRepository
from app.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger("labase.registration")


async def register_user(email: str, password: str, session: AsyncSession) -> None:
    """Create Supabase auth user + personal org atomically (saga with compensation)."""
    user_id_str = await register(email, password)
    try:
        repo = OrganizationRepository(session)
        await repo.create_with_owner(
            name=email,
            auth_user_id=uuid.UUID(user_id_str),
        )
    except Exception:
        log.warning("registration.org_creation_failed_compensating", user_id=user_id_str)
        supabase = get_admin_supabase()
        await asyncio.to_thread(supabase.auth.admin.delete_user, user_id_str)
        raise
