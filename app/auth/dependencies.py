from fastapi import Cookie, HTTPException, status
from supabase_auth import User

from app.supabase_client import supabase


async def get_current_user(access_token: str | None = Cookie(default=None)) -> User:
    if not access_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    try:
        response = supabase.auth.get_user(access_token)
        if response is None or response.user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
        return response.user
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


async def get_optional_user(access_token: str | None = Cookie(default=None)) -> User | None:
    if not access_token:
        return None
    try:
        response = supabase.auth.get_user(access_token)
        if response is None:
            return None
        return response.user
    except Exception:
        return None
