from functools import lru_cache

import jwt
from fastapi import Cookie, HTTPException, status

from app.auth.domain.service import AuthenticatedUser
from app.shared.config import get_settings


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    jwks_uri = f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(jwks_uri)


async def get_current_user(access_token: str | None = Cookie(default=None)) -> AuthenticatedUser:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(access_token)
        payload = jwt.decode(
            access_token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience="authenticated",
        )
        return AuthenticatedUser(id=payload["sub"], email=payload.get("email", ""))
    except jwt.PyJWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
