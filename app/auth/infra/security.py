from functools import lru_cache

import jwt
from fastapi import Cookie, HTTPException, Response, status

from app.auth.domain.service import AuthenticatedUser, AuthTokens, refresh_session
from app.auth.infra.cookies import set_auth_cookies
from app.shared.config import get_settings


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    jwks_uri = f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(jwks_uri)


def _decode(token: str) -> dict:
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
        payload = _decode(access_token)
    except jwt.ExpiredSignatureError:
        if not refresh_token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        try:
            tokens: AuthTokens = refresh_session(refresh_token)
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
        set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
        payload = _decode(tokens.access_token)
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return AuthenticatedUser(id=payload["sub"], email=payload.get("email", ""))
