from functools import lru_cache

import jwt
import structlog
from fastapi import Cookie, Depends, HTTPException, Response, status

from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, refresh_session
from apps.auth.infra.cookies import set_auth_cookies
from apps.shared.config import get_technical_settings

log = structlog.get_logger("labase.auth.security")


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    jwks_uri = f"{get_technical_settings().supabase_url}/auth/v1/.well-known/jwks.json"
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
) -> AuthenticatedUser:
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
            log.warning("auth.token_refresh_failed")
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
    return AuthenticatedUser(
        id=payload["sub"],
        email=payload.get("email", ""),
        access_token=access_token,
        is_admin=is_admin,
    )


async def get_current_admin(
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Gate for server-admin-only surfaces (the console).

    Anonymous callers already get 401 from ``get_current_user``. A signed-in non-admin gets a
    plain 404 — a 403 would confirm the protected surface exists.
    """
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


async def try_get_current_user(
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
) -> AuthenticatedUser | None:
    if not access_token:
        return None
    try:
        return await get_current_user(response, access_token, refresh_token)
    except HTTPException:
        return None
