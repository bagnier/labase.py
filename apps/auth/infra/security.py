from functools import lru_cache

import jwt
import structlog
from fastapi import (
    Cookie,
    Depends,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession
from supabase_auth.errors import AuthApiError

from apps.auth.contract.api_keys import API_KEY_PREFIX, ApiKeyQuery
from apps.auth.contract.events import ForbiddenAdminAccess
from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, refresh_session
from apps.auth.infra.cookies import set_auth_cookies
from apps.shared.bus import bus
from apps.shared.config import get_technical_settings
from apps.shared.persistence.database import get_admin_session

log = structlog.get_logger("labase.auth.security")


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def _resolve_api_key(token: str, session: AsyncSession) -> AuthenticatedUser:
    """Route an `lbk_...` bearer token to whoever answers ApiKeyQuery on the bus."""
    results = await bus.collect(ApiKeyQuery(token, session))
    principals = [p for p in results if p is not None]
    if not principals:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return principals[0]


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    jwks_uri = f"{get_technical_settings().supabase_api_url}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(jwks_uri)


def decode_jwt(token: str) -> dict:
    signing_key = _jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience="authenticated",
    )


async def get_current_user(
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> AuthenticatedUser:
    bearer = _bearer_token(authorization)
    if bearer is not None and bearer.startswith(API_KEY_PREFIX):
        principal = await _resolve_api_key(bearer, admin_session)
        structlog.contextvars.bind_contextvars(user_id=principal.id)
        return principal
    # A bearer GoTrue JWT is the machine twin of the cookie session (no refresh flow).
    access_token = access_token or bearer
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        payload = decode_jwt(access_token)
    except jwt.ExpiredSignatureError:
        if not refresh_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from None
        try:
            tokens: AuthTokens = await refresh_session(refresh_token)
        except Exception as exc:
            _report_refresh_failure(exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from exc
        set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
        access_token = tokens.access_token
        payload = decode_jwt(access_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    is_admin = payload.get("app_metadata", {}).get("role") == "admin"
    # Correlate every log line of this request with who made it — the unified logs viewer
    # filters the firehose by user_id (request_id is already bound by RequestLogger).
    structlog.contextvars.bind_contextvars(user_id=payload["sub"])
    return AuthenticatedUser(
        id=payload["sub"],
        email=payload.get("email", ""),
        access_token=access_token,
        is_admin=is_admin,
        claims=payload,
    )


def _is_expected_refresh_failure(exc: Exception) -> bool:
    """A stale, rotated, or absent refresh token is GoTrue answering a routine 'no' (a 4xx
    ``AuthApiError``) — the everyday end of a session, not a bug. Everything else (GoTrue
    unreachable, a 5xx, a network error, our own ``ValueError``) is a genuine failure."""
    return isinstance(exc, AuthApiError) and 400 <= exc.status < 500


def _report_refresh_failure(exc: Exception) -> None:
    """Log the lapse at the right level; ``log.exception`` is the capture seam for the rest."""
    if _is_expected_refresh_failure(exc):
        # A normal end-of-session — expected/operational, not degraded.
        log.info("auth.token_refresh_rejected", detail=str(exc))
        return
    log.exception("auth.token_refresh_failed")


async def get_current_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Gate for server-admin-only surfaces (the console).

    Anonymous callers already get 401 from ``get_current_user``. A signed-in non-admin gets a
    plain 404 — a 403 would confirm the protected surface exists.
    """
    if not user.is_admin:
        await bus.emit(ForbiddenAdminAccess(actor_id=user.id, path=request.url.path))
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


async def try_get_current_user(
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> AuthenticatedUser | None:
    if not access_token and _bearer_token(authorization) is None:
        return None
    try:
        return await get_current_user(
            response, access_token, refresh_token, authorization, admin_session
        )
    except HTTPException:
        return None
