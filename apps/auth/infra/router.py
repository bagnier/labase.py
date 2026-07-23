import contextlib
import time

import structlog
from fastapi import (
    APIRouter,
    Cookie,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from apps.auth.application import register_user
from apps.auth.contract.current import CurrentAdmin, CurrentUser, OptionalCurrentUser
from apps.auth.contract.events import (
    ConfirmationResent,
    EmailChanged,
    ImpersonationStarted,
    ImpersonationStopped,
    LoginFailed,
    MfaFailed,
    MfaVerified,
    OAuthFailed,
    OAuthSignedIn,
    PasskeyFailed,
    PasskeySignedIn,
    PasswordReset,
    RegisterFailed,
    SignedIn,
    SignedOut,
)
from apps.auth.contract.impersonation import (
    IMPERSONATION_MAX_SECONDS,
    IMPERSONATOR_COOKIE,
    IMPERSONATOR_DEADLINE_COOKIE,
    IMPERSONATOR_REFRESH_COOKIE,
    ImpersonationTargetNotFound,
    impersonation_tokens,
)
from apps.auth.contract.settings import UsersSettings
from apps.auth.domain.service import (
    OAUTH_PROVIDERS,
    AuthTokens,
    OAuthError,
    PasskeyError,
    PasswordUpdateError,
    TotpError,
    confirm_signup,
    exchange_oauth_code,
    login,
    logout,
    oauth_authorize_url,
    passkey_authentication_options,
    pkce_pair,
    request_password_reset,
    resend_confirmation,
    totp_challenge,
    update_password,
    verified_totp_factor,
    verify_passkey_authentication,
    verify_totp,
)
from apps.auth.infra.cookies import set_auth_cookies
from apps.auth.infra.security import decode_jwt
from apps.shared.config import get_technical_settings
from apps.shared.events.bus import events
from apps.shared.http import parse_body, wants_json
from apps.shared.http.addressing import client_ip
from apps.shared.http.limiter import rate_limit
from apps.shared.http.templates import templates
from apps.shared.settings import SettingsView

log = structlog.get_logger("labase.auth.router")

router = APIRouter()


_WEAK_PASSWORD_REASONS: dict[str, str] = {
    "too_short": "too short",
    "length": "too short",
    "too_simple": "too simple",
    "no_uppercase": "must contain an uppercase letter",
    "no_lowercase": "must contain a lowercase letter",
    "no_digit": "must contain a digit",
    "no_special": "must contain a special character",
    "pwned": "this password has been compromised",
}

_AUTH_ERROR_MESSAGES: dict[str, str] = {
    "email_exists": "An account already exists with this email.",
    "user_already_exists": "An account already exists with this email.",
    "email_address_not_authorized": "This email address is not authorized.",
    "signup_disabled": "Sign-ups are disabled.",
    "invalid_email": "Invalid email address.",
    "email_address_invalid": "Invalid email address.",
    "email_not_confirmed": "Please verify your email before signing in.",
    "user_banned": "This account is disabled.",
}


def _format_weak_password_reasons(reasons: list[str]) -> str:
    cleaned = [r.strip('"') for r in reasons]
    labels = [_WEAK_PASSWORD_REASONS.get(r, r) for r in cleaned]
    return ", ".join(labels) if labels else "requirements not met"


def _friendly_auth_error(e: AuthApiError) -> str:
    code = str(e.code) if e.code else ""
    msg = _AUTH_ERROR_MESSAGES.get(code, e.message)
    return msg.strip('"')


def _log_gotrue_failure(event: str, exc: Exception, **kw: object) -> None:
    """Log an auth-flow failure at the level its nature warrants.

    A 4xx GoTrue ``AuthApiError`` (expired/single-use link, wrong password, already-confirmed,
    rate-limited) is a normal user outcome → ``log.info``. Anything else (GoTrue unreachable, a
    5xx, an unexpected error) is a bug → ``log.exception``, which the capture seam tracks as an
    issue. Call from inside the ``except`` block so ``log.exception`` sees the live exception.
    """
    if isinstance(exc, AuthApiError) and 400 <= exc.status < 500:
        log.info(event, **kw)
    else:
        log.exception(event, **kw)


_INFO_MESSAGES: dict[str, str] = {
    "registered_pending_email": "Account created. Please verify your email before signing in.",
    "registered_active": "Account created. You can now sign in.",
    "password_reset": "Your password was changed. You can now sign in.",
    "email_change_failed": "This confirmation link is invalid or has expired. "
    "Please request the change again from your profile.",
    "confirm_failed": "This confirmation link is invalid or has expired. "
    "Sign in to receive a new one.",
    "account_deleted": "Your account has been deleted.",
}


def _safe_next(next_url: str | None) -> str:
    """Return next_url if it is a safe internal path, else /profile."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/profile"


def _enabled_oauth_providers(users_settings: SettingsView) -> list[str]:
    return [
        p for p in OAUTH_PROVIDERS if bool(getattr(users_settings, f"oauth_{p}_enabled", False))
    ]


def _client_ip(request: Request) -> str | None:
    return client_ip(request)


def _token_sub(token: str) -> str | None:
    """The ``sub`` (user id) claim of a freshly minted token — the actor of a just-completed auth
    ceremony, for attributing its business event when no request user is in hand yet."""
    return str(decode_jwt(token).get("sub", "")) or None


def _error_response(
    request: Request, template: str, message: str, status_code: int, **context: object
) -> Response:
    """The content-negotiated error tail shared by the form-backed auth endpoints: JSON
    ``{"detail": message}`` for API callers, else the template re-rendered with ``error``."""
    if wants_json(request):
        return JSONResponse({"detail": message}, status_code=status_code)
    return templates.TemplateResponse(
        request, template, {"error": message, **context}, status_code=status_code
    )


def _set_ephemeral_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    """Set a short-lived, HttpOnly, lax cookie honouring the ``cookies_secure`` config —
    the shape shared by the MFA hand-off, OAuth PKCE parking, and impersonation stash."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=get_technical_settings().cookies_secure,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: OptionalCurrentUser,
    users_settings: UsersSettings,
    info: str | None = None,
    next: str | None = None,
) -> Response:
    if current_user is not None:
        return RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "info": _INFO_MESSAGES.get(info or ""),
            "next": next,
            "oauth_providers": _enabled_oauth_providers(users_settings),
            "passkeys_enabled": bool(users_settings.passkeys_enabled),
        },
    )


@router.post("/login")
@rate_limit("10/minute")
async def login_endpoint(request: Request, users_settings: UsersSettings) -> Response:
    body = await parse_body(request)
    email = body.get("email", "")
    password = body.get("password", "")
    next = body.get("next", "")
    ip = _client_ip(request)
    if not email or not password:
        return _error_response(
            request,
            "login.html",
            "Email and password are required.",
            status.HTTP_400_BAD_REQUEST,
            email=email,
            next=next,
        )
    try:
        tokens = await login(email, password)
        if users_settings.two_factor_enabled:
            factor_id = await verified_totp_factor(tokens.access_token)
            if factor_id:
                return await _mfa_challenge_response(request, tokens, factor_id, next)
        # Past the 2FA gate: this is a completed password sign-in (the 2FA branch is marked by
        # MfaVerified). Record it — the freshly minted token carries the actor.
        await events.emit(SignedIn(actor_id=_token_sub(tokens.access_token)))
        if wants_json(request):
            resp = JSONResponse({"access_token": tokens.access_token, "token_type": "bearer"})
            set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
            return resp
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except AuthApiError as e:
        await events.emit(LoginFailed(email=email))
        code = str(e.code) if e.code else ""
        error = _AUTH_ERROR_MESSAGES.get(code, "Invalid email or password")
        # GoTrue blocks unconfirmed accounts itself; the app adds the way out.
        offer_resend = code == "email_not_confirmed" and bool(
            users_settings.resend_confirmation_enabled
        )
        return _error_response(
            request,
            "login.html",
            error,
            status.HTTP_401_UNAUTHORIZED,
            email=email,
            next=next,
            resend_email=offer_resend and email,
        )
    except Exception:
        log.exception("auth.login_error", ip=ip, email=email)
        return _error_response(
            request,
            "login.html",
            "A system error occurred. Please try again later.",
            status.HTTP_503_SERVICE_UNAVAILABLE,
            email=email,
            next=next,
        )


_MFA_COOKIE = "mfa_access_token"
_MFA_REFRESH_COOKIE = "mfa_refresh_token"
_MFA_MAX_SECONDS = 300


async def _mfa_challenge_response(
    request: Request, tokens: AuthTokens, factor_id: str, next: str
) -> Response:
    """Correct password, TOTP enrolled: hold the AAL1 tokens in short-lived
    cookies and ask for the authenticator code before issuing the session."""
    challenge_id = await totp_challenge(tokens.access_token, factor_id)
    if wants_json(request):
        resp: Response = JSONResponse(
            {"mfa_required": True, "factor_id": factor_id, "challenge_id": challenge_id}
        )
    else:
        resp = templates.TemplateResponse(
            request,
            "mfa.html",
            {"factor_id": factor_id, "challenge_id": challenge_id, "next": next},
        )
    _set_ephemeral_cookie(resp, _MFA_COOKIE, tokens.access_token, _MFA_MAX_SECONDS)
    _set_ephemeral_cookie(resp, _MFA_REFRESH_COOKIE, tokens.refresh_token, _MFA_MAX_SECONDS)
    return resp


@router.post("/mfa")
@rate_limit("10/minute")
async def mfa_verify_endpoint(
    request: Request,
    mfa_access_token: str | None = Cookie(default=None),
) -> Response:
    body = await parse_body(request)
    code = str(body.get("code", "")).strip()
    factor_id = str(body.get("factor_id", ""))
    if not mfa_access_token or not factor_id:
        return RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    challenge_id = str(body.get("challenge_id", ""))
    next = str(body.get("next", ""))
    try:
        tokens = await verify_totp(mfa_access_token, factor_id, challenge_id, code)
    except TotpError:
        await events.emit(MfaFailed(factor_id=factor_id))
        error = "That code did not work. Try the next one from your app."
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=status.HTTP_401_UNAUTHORIZED)
        # The challenge may be consumed: mint a fresh one for the retry.
        challenge_id = await totp_challenge(mfa_access_token, factor_id)
        return templates.TemplateResponse(
            request,
            "mfa.html",
            {"factor_id": factor_id, "challenge_id": challenge_id, "next": next, "error": error},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    await events.emit(MfaVerified(actor_id=_token_sub(tokens.access_token), factor_id=factor_id))
    if wants_json(request):
        resp: Response = JSONResponse({"access_token": tokens.access_token, "token_type": "bearer"})
    else:
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
    resp.delete_cookie(_MFA_COOKIE)
    resp.delete_cookie(_MFA_REFRESH_COOKIE)
    return resp


@router.post("/logout")
async def logout_endpoint(access_token: str | None = Cookie(default=None)) -> Response:
    if access_token:
        await logout(access_token)
        # Attribute the sign-out to the account holder — but the cookie may be expired by now, so
        # a failed decode must not turn a logout into a 500; record it with no actor instead.
        actor_id = None
        with contextlib.suppress(Exception):
            actor_id = str(decode_jwt(access_token).get("sub", "")) or None
        await events.emit(SignedOut(actor_id=actor_id))
    resp = RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


# ── Passkey sign-in (WebAuthn, discoverable credentials) ───────────────────────
# The login page's JS drives navigator.credentials.get(); these two endpoints
# proxy GoTrue's anonymous authentication ceremony and land the session cookies.


def _ensure_passkeys_enabled(users_settings: SettingsView) -> None:
    if not users_settings.passkeys_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/passkeys/options")
@rate_limit("10/minute")
async def passkey_options_endpoint(request: Request, users_settings: UsersSettings) -> Response:
    _ensure_passkeys_enabled(users_settings)
    try:
        return JSONResponse(await passkey_authentication_options())
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/passkeys/verify")
@rate_limit("10/minute")
async def passkey_verify_endpoint(request: Request, users_settings: UsersSettings) -> Response:
    _ensure_passkeys_enabled(users_settings)
    body = await parse_body(request)
    challenge_id = str(body.get("challenge_id", ""))
    credential = body.get("credential")
    if not challenge_id or not isinstance(credential, dict):
        return JSONResponse(
            {"detail": "challenge_id and credential are required."},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        tokens = await verify_passkey_authentication(challenge_id, credential)
    except PasskeyError as e:
        await events.emit(PasskeyFailed())
        return JSONResponse({"detail": str(e)}, status_code=status.HTTP_401_UNAUTHORIZED)
    claims = decode_jwt(tokens.access_token)
    await events.emit(PasskeySignedIn(actor_id=str(claims.get("sub", "")) or None))
    resp = JSONResponse(
        {
            "access_token": tokens.access_token,
            "token_type": "bearer",
            "redirect": _safe_next(str(body.get("next", "") or "")),
        }
    )
    set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
    return resp


# ── OAuth social sign-in ────────────────────────────────────────────────────────
# GoTrue drives the provider; the app only holds the PKCE verifier between the
# redirect and the callback, parked in a short-lived cookie (the MFA pattern —
# the process keeps no session state).

_OAUTH_VERIFIER_COOKIE = "oauth_code_verifier"
_OAUTH_NEXT_COOKIE = "oauth_next"
_OAUTH_MAX_SECONDS = 300


def _clear_oauth_cookies(resp: Response) -> None:
    resp.delete_cookie(_OAUTH_VERIFIER_COOKIE)
    resp.delete_cookie(_OAUTH_NEXT_COOKIE)


@router.get("/oauth/{provider}")
@rate_limit("10/minute")
async def oauth_start(
    request: Request, provider: str, users_settings: UsersSettings, next: str = Query(default="")
) -> Response:
    if provider not in _enabled_oauth_providers(users_settings):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    verifier, challenge = pkce_pair()
    redirect_to = str(request.base_url).rstrip("/") + "/auth/callback"
    resp = RedirectResponse(
        oauth_authorize_url(provider, redirect_to, challenge),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    _set_ephemeral_cookie(resp, _OAUTH_VERIFIER_COOKIE, verifier, _OAUTH_MAX_SECONDS)
    _set_ephemeral_cookie(resp, _OAUTH_NEXT_COOKIE, next, _OAUTH_MAX_SECONDS)
    return resp


def _oauth_failure(request: Request, message: str, users_settings: SettingsView) -> Response:
    resp = templates.TemplateResponse(
        request,
        "login.html",
        {"error": message, "oauth_providers": _enabled_oauth_providers(users_settings)},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )
    _clear_oauth_cookies(resp)
    return resp


@router.get("/callback")
@rate_limit("10/minute")
async def oauth_callback(
    request: Request,
    users_settings: UsersSettings,
    code: str = Query(default=""),
    error_description: str = Query(default=""),
    oauth_code_verifier: str | None = Cookie(default=None),
    oauth_next: str | None = Cookie(default=None),
) -> Response:
    """Land the browser back from GoTrue: exchange the PKCE code for a session.

    Account merge is GoTrue's: a provider identity whose verified email matches an
    existing account is linked into it (auth.identities), never duplicated.
    """
    if not code or not oauth_code_verifier:
        log.warning("auth.oauth_callback_rejected", has_code=bool(code))
        return _oauth_failure(
            request,
            error_description or "Sign-in with the provider failed. Please try again.",
            users_settings,
        )
    try:
        # The org and admin bootstrap are provisioned by the signup trigger the moment GoTrue
        # creates the account, so a first-visit ``is_new`` no longer needs an app-side hook here.
        tokens, _is_new = await exchange_oauth_code(code, oauth_code_verifier)
    except OAuthError as e:
        await events.emit(OAuthFailed())
        return _oauth_failure(request, str(e), users_settings)
    claims = decode_jwt(tokens.access_token)
    await events.emit(OAuthSignedIn(actor_id=str(claims.get("sub", "")) or None))
    next = oauth_next or ""
    if users_settings.two_factor_enabled:
        factor_id = await verified_totp_factor(tokens.access_token)
        if factor_id:
            resp = await _mfa_challenge_response(request, tokens, factor_id, next)
            _clear_oauth_cookies(resp)
            return resp
    resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
    _clear_oauth_cookies(resp)
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(
    request: Request, users_settings: UsersSettings, next: str | None = None
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "register.html",
        {"next": next, "oauth_providers": _enabled_oauth_providers(users_settings)},
    )


@router.post("/register")
@rate_limit("5/minute")
async def register_endpoint(request: Request) -> Response:
    body = await parse_body(request)
    email = body.get("email", "")
    password = body.get("password", "")
    next = body.get("next", "")
    ip = _client_ip(request)
    if not email or not password:
        return _error_response(
            request,
            "register.html",
            "Email and password are required.",
            status.HTTP_400_BAD_REQUEST,
            email=email,
            next=next,
        )
    try:
        result = await register_user(email, password)
        if wants_json(request):
            return JSONResponse(
                {"message": "Account created. Please verify your email."},
                status_code=status.HTTP_201_CREATED,
            )
        info_key = (
            "registered_pending_email" if result.access_token is None else "registered_active"
        )
        login_url = f"/auth/login?info={info_key}"
        if next:
            login_url += f"&next={next}"
        redirect = RedirectResponse(login_url, status_code=status.HTTP_303_SEE_OTHER)
        redirect.delete_cookie("access_token")
        redirect.delete_cookie("refresh_token")
        return redirect
    except AuthWeakPasswordError as e:
        error = f"Password too weak: {_format_weak_password_reasons(e.reasons)}"
    except AuthApiError as e:
        error = _friendly_auth_error(e)
        log.warning("auth.register_failed", ip=ip, email=email, code=str(e.code))
        await events.emit(RegisterFailed(email=email))
    except Exception:
        log.exception("auth.register_error", ip=ip, email=email)
        error = "An unexpected error occurred."
    return _error_response(
        request, "register.html", error, status.HTTP_400_BAD_REQUEST, email=email, next=next
    )


@router.post("/impersonate")
async def impersonate_endpoint(
    request: Request,
    admin: CurrentAdmin,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
) -> Response:
    body = await parse_body(request)
    email = str(body.get("email", "")).strip().lower()
    if not email or email == admin.email.lower() or not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Pick another user's email."
        )
    try:
        tokens = await impersonation_tokens(email)
    except ImpersonationTargetNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No user with this email."
        ) from None
    await events.emit(ImpersonationStarted(actor_id=admin.id, target_email=email))
    if wants_json(request):
        resp: Response = JSONResponse({"impersonating": email})
    else:
        resp = RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    # Stash the admin's own session, then become the target — everything time-boxed:
    # when these cookies expire the disguise and the stash die together. The deadline cookie
    # carries the absolute end of the window so a mid-window token refresh re-caps the target
    # session to the time it has left instead of re-minting a full-length login (see security.py).
    deadline = int(time.time()) + IMPERSONATION_MAX_SECONDS
    _set_ephemeral_cookie(resp, IMPERSONATOR_COOKIE, access_token, IMPERSONATION_MAX_SECONDS)
    _set_ephemeral_cookie(
        resp, IMPERSONATOR_REFRESH_COOKIE, refresh_token or "", IMPERSONATION_MAX_SECONDS
    )
    _set_ephemeral_cookie(
        resp, IMPERSONATOR_DEADLINE_COOKIE, str(deadline), IMPERSONATION_MAX_SECONDS
    )
    _set_ephemeral_cookie(resp, "access_token", tokens.access_token, IMPERSONATION_MAX_SECONDS)
    _set_ephemeral_cookie(resp, "refresh_token", tokens.refresh_token, IMPERSONATION_MAX_SECONDS)
    return resp


@router.post("/impersonate/stop")
async def stop_impersonation_endpoint(
    request: Request,
    current_user: CurrentUser,
) -> Response:
    stash = request.cookies.get(IMPERSONATOR_COOKIE)
    refresh_stash = request.cookies.get(IMPERSONATOR_REFRESH_COOKIE, "")
    if not stash:
        return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    admin_id = None
    try:
        admin_id = decode_jwt(stash)["sub"]
    except Exception:  # expired stash: still drop the disguise, record without the id
        log.warning("auth.impersonation_stash_invalid")
    await events.emit(ImpersonationStopped(actor_id=admin_id, target_email=current_user.email))
    if wants_json(request):
        resp: Response = JSONResponse({"impersonating": None})
    else:
        resp = RedirectResponse("/console", status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, stash, refresh_stash)
    resp.delete_cookie(IMPERSONATOR_COOKIE)
    resp.delete_cookie(IMPERSONATOR_REFRESH_COOKIE)
    resp.delete_cookie(IMPERSONATOR_DEADLINE_COOKIE)
    return resp


@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "forgot_password.html", {})


@router.post("/forgot-password")
@rate_limit("5/minute")
async def forgot_password_endpoint(request: Request) -> Response:
    body = await parse_body(request)
    email = str(body.get("email", "")).strip()
    # Same response whether the account exists or not — no user enumeration.
    sent_message = "If an account exists for this address, a reset email is on its way."
    if email:
        try:
            await request_password_reset(email)
        except Exception as e:
            _log_gotrue_failure("auth.password_reset_request_failed", e)
    if wants_json(request):
        return JSONResponse({"message": sent_message})
    return templates.TemplateResponse(request, "forgot_password.html", {"info": sent_message})


@router.post("/resend-confirmation")
@rate_limit("10/minute")
async def resend_confirmation_endpoint(request: Request, users_settings: UsersSettings) -> Response:
    """Send the signup confirmation again — the way out for an unconfirmed account.

    Neutral answer whatever happens (no account enumeration), like forgot-password.
    """
    if not users_settings.resend_confirmation_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    email = str(body.get("email", "")).strip().lower()
    sent_message = "If an account exists for this address, a confirmation email is on its way."
    if email:
        try:
            await resend_confirmation(email)
            await events.emit(ConfirmationResent(email=email))
        except Exception as e:
            _log_gotrue_failure("auth.confirmation_resend_failed", e)
    if wants_json(request):
        return JSONResponse({"message": sent_message})
    return templates.TemplateResponse(request, "login.html", {"info": sent_message, "email": email})


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(request: Request, token_hash: str = Query(default="")) -> Response:
    if not token_hash:
        return RedirectResponse("/auth/forgot-password", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request, "reset_password.html", {"token_hash": token_hash})


@router.post("/reset-password")
@rate_limit("10/minute")
async def reset_password_endpoint(request: Request) -> Response:
    body = await parse_body(request)
    token_hash = str(body.get("token_hash", ""))
    password = str(body.get("password", ""))
    ip = _client_ip(request)
    try:
        tokens = await confirm_signup(token_hash, type="recovery")
        await update_password(tokens.access_token, password)
    except PasswordUpdateError as e:
        # The recovery token is single-use and already consumed: a new link is needed.
        error = f"{e}. Please request a new reset link."
        return _error_response(request, "forgot_password.html", error, status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        _log_gotrue_failure("auth.password_reset_failed", e, ip=ip)
        error = "This reset link is invalid or has expired. Please request a new one."
        return _error_response(request, "forgot_password.html", error, status.HTTP_400_BAD_REQUEST)
    # The recovery session is dropped on purpose: the user signs in with the new password — but
    # decode its ``sub`` first, so the reset lands on the trail attributed to the account holder.
    await events.emit(PasswordReset(actor_id=_token_sub(tokens.access_token)))
    if wants_json(request):
        return JSONResponse({"message": _INFO_MESSAGES["password_reset"]})
    return RedirectResponse(
        "/auth/login?info=password_reset", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/confirm-email")
@rate_limit("10/minute")
async def confirm_email_endpoint(request: Request, token_hash: str = Query(default="")) -> Response:
    """Finalize an email change from the link mailed to the new address.

    Anonymous on purpose — the single-use token IS the credential (the reader of
    the new mailbox proves ownership), and the requesting session may be gone.
    """
    try:
        tokens = await confirm_signup(token_hash, type="email_change")
    except Exception as e:
        _log_gotrue_failure("auth.email_change_failed", e, token_hash=token_hash[:8])
        return RedirectResponse(
            "/auth/login?info=email_change_failed", status_code=status.HTTP_303_SEE_OTHER
        )
    claims = decode_jwt(tokens.access_token)
    await events.emit(EmailChanged(actor_id=str(claims.get("sub", "")) or None))
    resp = RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
    return resp


@router.get("/confirm")
@rate_limit("10/minute")
async def confirm_endpoint(
    request: Request,
    token_hash: str = Query(...),
    type: str = Query(...),
    next: str = Query(default="/profile"),
) -> Response:
    """Handle Supabase email confirmation links (?token_hash=...&type=signup)."""
    try:
        # UserCreated (and thus the personal org) was recorded by the signup trigger when the
        # account row was first created; confirming an email adds no new provisioning here.
        tokens = await confirm_signup(token_hash, type)
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except Exception as e:
        _log_gotrue_failure("auth.confirm_error", e, token_hash=token_hash[:8])
        return RedirectResponse(
            "/auth/login?info=confirm_failed", status_code=status.HTTP_303_SEE_OTHER
        )
