"""Auth application services — registration use-case.

Orchestrates sign-up: calls the auth domain service, emits ``UserCreated`` so the org
context takes over, and compensates (deletes the orphan auth user) if org creation fails.
HTTP routers call into here and only map results/errors to responses.
"""

import asyncio

import structlog

from app.auth.contract.events import UserCreated
from app.auth.domain.service import RegisterResult, register
from app.auth.infra.security import decode_jwt
from app.integration import host
from app.shared.persistence.supabase import get_admin_supabase

log = structlog.get_logger("labase.auth")


async def register_user(email: str, password: str) -> RegisterResult:
    """Create the auth user and, if no email confirmation is required, bootstrap their org."""
    result = await register(email, password)
    if result.access_token is None:
        return result
    try:
        await host.events.emit(
            UserCreated(user_id=result.user_id, email=email, access_token=result.access_token)
        )
    except Exception:
        log.warning("registration.org_creation_failed_compensating", user_id=result.user_id)
        supabase = get_admin_supabase()
        await asyncio.to_thread(supabase.auth.admin.delete_user, result.user_id)
        raise
    return result


async def confirm_user(access_token: str) -> None:
    """Bootstrap the org for a user whose email was just confirmed."""
    claims = decode_jwt(access_token)
    await host.events.emit(
        UserCreated(user_id=claims["sub"], email=claims.get("email", ""), access_token=access_token)
    )
