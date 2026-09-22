import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
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
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.api_keys import API_KEY_PREFIX, ApiKeyQuery
from apps.auth.contract.user import AuthenticatedUser
from apps.auth.domain.service import AuthTokens, refresh_session
from apps.auth.infra.cookies import set_auth_cookies
from apps.shared import clock
from apps.shared.integration.contribs import contribs
from apps.shared.logs.dependency import is_refusal
from apps.shared.persistence.database import get_user_session
from apps.shared.persistence.rls import clear_rls_context, set_rls_context
from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import get_settings

log = structlog.get_logger(__name__)


def _bearer_token(authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


async def _resolve_api_key(token: str, session: AsyncSession) -> AuthenticatedUser:
    """Route an `lbk_...` bearer token to whoever contributes an answer to ApiKeyQuery.

    Unlike ``contribs.collect``'s general log-and-skip policy (right for a dashboard card, whose
    absence hurts nobody), a raising provider here must not be read as "no key matched": that
    would answer a valid key with a wrong-password 401 instead of the 503 a broken dependency
    earns.
    """
    query = ApiKeyQuery(token, session)
    for provider in contribs.providers(ApiKeyQuery):
        try:
            principal = await provider(query)
        except Exception as exc:
            log.exception("auth.api_key_provider_failed", provider=repr(provider))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="API key verification unavailable",
            ) from exc
        if principal is not None:
            return principal
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


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


@asynccontextmanager
async def _before_identity(session: AsyncSession) -> AsyncIterator[None]:
    """Reads made while who is asking is not known yet: the app's role with claims naming nobody,
    never a BYPASSRLS connection — what they need goes through functions made for it. Undone
    after, so the session carries no borrowed identity into the request's own context."""
    await set_rls_context(session, {"role": "anon"})
    try:
        yield
    finally:
        await clear_rls_context(session)


def _short_of_aal2(payload: dict) -> bool:
    """Whether the token could owe a second factor at all — free to answer, so the database is
    asked only then."""
    return payload.get("aal") != "aal2" and bool(get_settings("users").view().two_factor_enabled)


async def _second_factor_owed(payload: dict, session: AsyncSession) -> bool:
    """Whether this token stopped short of the second factor its account has enrolled.

    GoTrue mints a working ``aal1`` token before the TOTP step-up — the one the challenge relays.
    Accepting it here would make the password alone a session; with 2FA switched off server-wide,
    sign-in skips the step-up, so ``aal1`` is the only level there is."""
    if not _short_of_aal2(payload):
        return False
    enrolled = await session.scalar(
        text("select second_factor_enrolled(:uid)").bindparams(uid=uuid.UUID(payload["sub"]))
    )
    return bool(enrolled)


async def _impersonated_by_an_admin(stash: str | None, session: AsyncSession) -> bool:
    """Whether the stashed impersonator token is a live admin session that owes no second factor.

    Impersonation mints the target's session through a magic link — ``aal1`` by construction — so
    a disguise over an enrolled account holds only on the admin's word, read from their own token:
    the cookie alone is a value anyone can set."""
    if not stash:
        return False
    try:
        admin = decode_jwt(stash)
    except jwt.PyJWTError:
        return False
    if admin.get("app_metadata", {}).get("role") != "admin":
        return False
    return not await _second_factor_owed(admin, session)


def _impersonation_remaining(deadline: str | None) -> int | None:
    """Seconds left in the impersonation window, or ``None`` when not impersonating.

    The value can be ``<= 0`` (window elapsed); callers refuse the refresh in that case. A
    malformed cookie is treated as no window rather than trusting an unbounded session."""
    if not deadline:
        return None
    try:
        return int(deadline) - int(clock.now().timestamp())
    except ValueError:
        return None


async def get_current_user(
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    impersonator_deadline: str | None = Cookie(default=None),
    impersonator_access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_user_session),
) -> AuthenticatedUser:
    bearer = _bearer_token(authorization)
    if bearer is not None and bearer.startswith(API_KEY_PREFIX):
        async with _before_identity(session):
            principal = await _resolve_api_key(bearer, session)
        structlog.contextvars.bind_contextvars(user_id=str(principal.id))
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
        # A refresh while impersonating must not outlive the impersonation window: re-emitting
        # the default long-lived login cookies here would silently extend the disguise past
        # IMPERSONATION_MAX_SECONDS. Cap the re-emitted session to the box's remaining time, and
        # refuse once the box has closed so the target session dies with the banner.
        impersonation_ttl = _impersonation_remaining(impersonator_deadline)
        if impersonation_ttl is not None and impersonation_ttl <= 0:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Impersonation window elapsed"
            ) from None
        try:
            tokens: AuthTokens = await refresh_session(refresh_token)
        except Exception as exc:
            _report_refresh_failure(exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
            ) from exc
        set_auth_cookies(
            response, tokens.access_token, tokens.refresh_token, max_age=impersonation_ttl
        )
        access_token = tokens.access_token
        payload = decode_jwt(access_token)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    refused = False
    if _short_of_aal2(payload):
        async with _before_identity(session):
            refused = await _second_factor_owed(payload, session) and not (
                await _impersonated_by_an_admin(impersonator_access_token, session)
            )
    if refused:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Second factor required"
        )
    is_admin = payload.get("app_metadata", {}).get("role") == "admin"
    # Correlate every log line of this request with who made it — the unified logs viewer
    # filters the log sink by user_id (request_id is already bound by RequestLogger).
    structlog.contextvars.bind_contextvars(user_id=payload["sub"])
    return AuthenticatedUser(
        id=uuid.UUID(payload["sub"]),
        email=payload.get("email", ""),
        access_token=access_token,
        is_admin=is_admin,
        claims=payload,
    )


def _report_refresh_failure(exc: Exception) -> None:
    """Log the lapse at the level its nature warrants — the base's verdict, not a second copy.

    A stale, rotated or absent refresh token is GoTrue answering a routine 'no' (a 4xx): the
    everyday end of a session for every returning user whose token turned over, not a surprise —
    so it earns no line at all, not even ``log_dependency_failure``'s usual ``info`` for a
    refusal. Everything else — GoTrue unreachable, a 5xx, a network error, our own
    ``ValueError`` — is a broken dependency, which the capture seam tracks as an issue.
    """
    if is_refusal(exc):
        return
    log.exception("auth.token_refresh_failed", exc_info=exc, detail=str(exc))


async def get_current_admin(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> AuthenticatedUser:
    """Gate for server-admin-only surfaces (the console).

    Anonymous callers already get 401 from ``get_current_user``. A signed-in non-admin gets a
    plain 404 — a 403 would confirm the protected surface exists.
    """
    if not user.is_admin:
        # A refusal, not a fact: nothing changed, and a log line outlives the raise below without
        # needing a transaction of its own.
        log.warning("auth.forbidden_admin_access", user_id=str(user.id), path=request.url.path)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return user


async def try_get_current_user(
    response: Response,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
    authorization: str | None = Header(default=None),
    impersonator_deadline: str | None = Cookie(default=None),
    impersonator_access_token: str | None = Cookie(default=None),
    session: AsyncSession = Depends(get_user_session),
) -> AuthenticatedUser | None:
    if not access_token and _bearer_token(authorization) is None:
        return None
    try:
        return await get_current_user(
            response,
            access_token,
            refresh_token,
            authorization,
            impersonator_deadline,
            impersonator_access_token,
            session,
        )
    except HTTPException:
        return None
