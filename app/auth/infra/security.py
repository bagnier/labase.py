from functools import lru_cache

import jwt
import structlog
from fastapi import Cookie, HTTPException, Response, status

from app.auth.domain.service import AuthenticatedUser, AuthTokens, refresh_session
from app.auth.infra.cookies import set_auth_cookies
from app.shared.config import get_settings

log = structlog.get_logger("labase.auth.security")


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    jwks_uri = f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"
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
    return AuthenticatedUser(
        id=payload["sub"], email=payload.get("email", ""), access_token=access_token
    )


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
