"""Registration use-case — orchestrates sign-up across contexts via the event bus.

``auth`` creates the auth user; this orchestrator emits ``UserCreated`` so ``org`` creates
the personal org (returning its id), then schedules ``OrgCreated`` so apps seed welcome
data post-commit. HTTP routers call into here and only map results/errors to responses;
the orchestration (events, compensation, background scheduling) lives here.
"""

import asyncio
import uuid

import structlog
from fastapi import BackgroundTasks

from app.auth.contract.events import UserCreated
from app.auth.domain.service import RegisterResult, register
from app.auth.infra.security import decode_jwt
from app.integration import host
from app.organizations.contract.events import OrgCreated
from app.shared.config import get_settings
from app.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger("labase.registration")


async def register_user(email: str, password: str, bg: BackgroundTasks) -> RegisterResult:
    """Create the auth user and, if no email confirmation is required, bootstrap their org.

    When confirmation is pending (``access_token is None``) the org is created later, at
    the confirmation callback (:func:`confirm_user`).
    """
    result = await register(email, password)
    if result.access_token is None:
        return result
    org_id = await _create_org(result.user_id, email, compensate=True)
    _schedule_seed(bg, org_id, result.access_token)
    return result


async def confirm_user(access_token: str, bg: BackgroundTasks) -> None:
    """Bootstrap the org for a user whose email was just confirmed."""
    claims = decode_jwt(access_token)
    org_id = await _create_org(claims["sub"], claims.get("email", ""), compensate=False)
    _schedule_seed(bg, org_id, access_token)


async def _create_org(user_id: str, email: str, *, compensate: bool) -> uuid.UUID:
    """Emit ``UserCreated`` so the org context creates the org; return its id.

    On failure during sign-up (``compensate``), delete the just-created auth user so no
    orphan account survives the missing org.
    """
    try:
        (org_id,) = await host.events.emit(UserCreated(user_id=user_id, email=email))
    except Exception:
        if compensate:
            log.warning("registration.org_creation_failed_compensating", user_id=user_id)
            supabase = get_admin_supabase()
            await asyncio.to_thread(supabase.auth.admin.delete_user, user_id)
        raise
    assert isinstance(org_id, uuid.UUID)
    return org_id


def _schedule_seed(bg: BackgroundTasks, org_id: uuid.UUID, access_token: str) -> None:
    """Fire ``OrgCreated`` post-commit so apps seed the new org.

    Skipped under the test schema: BDD scenarios start from an empty org (seeding is
    exercised against real Supabase).
    """
    if get_settings().db_schema == "test":
        return
    bg.add_task(host.events.emit, OrgCreated(org_id=org_id, access_token=access_token))
