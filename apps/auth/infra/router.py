import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from apps.auth.application import confirm_user, register_user
from apps.auth.contract import settings
from apps.auth.contract.current import CurrentAdmin, CurrentUser, OptionalCurrentUser
from apps.auth.contract.impersonation import (
    IMPERSONATION_MAX_SECONDS,
    IMPERSONATOR_COOKIE,
    IMPERSONATOR_REFRESH_COOKIE,
    ImpersonationTargetNotFound,
    impersonation_tokens,
)
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
from apps.shared.http import parse_body, wants_json
from apps.shared.http.limiter import rate_limit
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit

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


_INFO_MESSAGES: dict[str, str] = {
    "registered_pending_email": "Account created. Please verify your email before signing in.",
    "registered_active": "Account created. You can now sign in.",
    "password_reset": "Your password was changed. You can now sign in.",
    "email_change_failed": "This confirmation link is invalid or has expired. "
    "Please request the change again from your profile.",
    "account_deleted": "Your account has been deleted.",
}


def _safe_next(next_url: str | None) -> str:
    """Return next_url if it is a safe internal path, else /profile."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/profile"


def _enabled_oauth_providers() -> list[str]:
    return [p for p in OAUTH_PROVIDERS if bool(getattr(settings, f"oauth_{p}_enabled", False))]


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: OptionalCurrentUser,
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
            "oauth_providers": _enabled_oauth_providers(),
            "passkeys_enabled": bool(settings.passkeys_enabled),
        },
    )


@router.post("/login")
@rate_limit("10/minute")
async def login_endpoint(request: Request, bg: BackgroundTasks) -> Response:
    body = await parse_body(request)
    email = body.get("email", "")
    password = body.get("password", "")
    next = body.get("next", "")
    ip = request.client.host if request.client else None
    if not email or not password:
        if wants_json(request):
            return JSONResponse(
                {"detail": "Email and password are required."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Email and password are required.", "email": email, "next": next},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        tokens = await login(email, password)
        if settings.two_factor_enabled:
            factor_id = await verified_totp_factor(tokens.access_token)
            if factor_id:
                return await _mfa_challenge_response(request, tokens, factor_id, next)
        if wants_json(request):
            resp = JSONResponse({"access_token": tokens.access_token, "token_type": "bearer"})
            set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
            return resp
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except AuthApiError as e:
        audit(bg, "auth.login_failed", level="warning", ip=ip, email=email)
        code = str(e.code) if e.code else ""
        error = _AUTH_ERROR_MESSAGES.get(code, "Invalid email or password")
        # GoTrue blocks unconfirmed accounts itself; the app adds the way out.
        offer_resend = code == "email_not_confirmed" and bool(settings.resend_confirmation_enabled)
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=status.HTTP_401_UNAUTHORIZED)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error, "email": email, "next": next, "resend_email": offer_resend and email},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception:
        log.exception("auth.login_error", ip=ip, email=email)
        if wants_json(request):
            return JSONResponse(
                {"detail": "A system error occurred. Please try again later."},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "error": "A system error occurred. Please try again later.",
                "email": email,
                "next": next,
            },
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
    for name, value in (
        (_MFA_COOKIE, tokens.access_token),
        (_MFA_REFRESH_COOKIE, tokens.refresh_token),
    ):
        resp.set_cookie(
            name,
            value,
            max_age=_MFA_MAX_SECONDS,
            httponly=True,
            samesite="lax",
            secure=get_technical_settings().cookies_secure,
        )
    return resp


@router.post("/mfa")
@rate_limit("10/minute")
async def mfa_verify_endpoint(
    request: Request,
    bg: BackgroundTasks,
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
        audit(bg, "auth.mfa_failed", level="warning", factor_id=factor_id)
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
    audit(bg, "auth.mfa_verified", factor_id=factor_id)
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
    resp = RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


# ── Passkey sign-in (WebAuthn, discoverable credentials) ───────────────────────
# The login page's JS drives navigator.credentials.get(); these two endpoints
# proxy GoTrue's anonymous authentication ceremony and land the session cookies.


def _ensure_passkeys_enabled() -> None:
    if not settings.passkeys_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/passkeys/options")
@rate_limit("10/minute")
async def passkey_options_endpoint(request: Request) -> Response:
    _ensure_passkeys_enabled()
    try:
        return JSONResponse(await passkey_authentication_options())
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/passkeys/verify")
@rate_limit("10/minute")
async def passkey_verify_endpoint(request: Request, bg: BackgroundTasks) -> Response:
    _ensure_passkeys_enabled()
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
        audit(bg, "auth.passkey_failed", level="warning")
        return JSONResponse({"detail": str(e)}, status_code=status.HTTP_401_UNAUTHORIZED)
    claims = decode_jwt(tokens.access_token)
    audit(bg, "auth.passkey_signed_in", user_id=str(claims.get("sub", "")))
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


@router.get("/oauth/{provider}")
@rate_limit("10/minute")
async def oauth_start(request: Request, provider: str, next: str = Query(default="")) -> Response:
    if provider not in _enabled_oauth_providers():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    verifier, challenge = pkce_pair()
    redirect_to = str(request.base_url).rstrip("/") + "/auth/callback"
    resp = RedirectResponse(
        oauth_authorize_url(provider, redirect_to, challenge),
        status_code=status.HTTP_303_SEE_OTHER,
    )
    for name, value in ((_OAUTH_VERIFIER_COOKIE, verifier), (_OAUTH_NEXT_COOKIE, next)):
        resp.set_cookie(
            name,
            value,
            max_age=_OAUTH_MAX_SECONDS,
            httponly=True,
            samesite="lax",
            secure=get_technical_settings().cookies_secure,
        )
    return resp


def _oauth_failure(request: Request, message: str) -> Response:
    resp = templates.TemplateResponse(
        request,
        "login.html",
        {"error": message, "oauth_providers": _enabled_oauth_providers()},
        status_code=status.HTTP_401_UNAUTHORIZED,
    )
    resp.delete_cookie(_OAUTH_VERIFIER_COOKIE)
    resp.delete_cookie(_OAUTH_NEXT_COOKIE)
    return resp


@router.get("/callback")
@rate_limit("10/minute")
async def oauth_callback(
    request: Request,
    bg: BackgroundTasks,
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
            request, error_description or "Sign-in with the provider failed. Please try again."
        )
    try:
        tokens = await exchange_oauth_code(code, oauth_code_verifier)
    except OAuthError as e:
        audit(bg, "auth.oauth_failed", level="warning")
        return _oauth_failure(request, str(e))
    await confirm_user(tokens.access_token)  # first visit bootstraps the personal org
    claims = decode_jwt(tokens.access_token)
    audit(bg, "auth.oauth_signed_in", user_id=str(claims.get("sub", "")))
    next = oauth_next or ""
    if settings.two_factor_enabled:
        factor_id = await verified_totp_factor(tokens.access_token)
        if factor_id:
            resp = await _mfa_challenge_response(request, tokens, factor_id, next)
            resp.delete_cookie(_OAUTH_VERIFIER_COOKIE)
            resp.delete_cookie(_OAUTH_NEXT_COOKIE)
            return resp
    resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
    resp.delete_cookie(_OAUTH_VERIFIER_COOKIE)
    resp.delete_cookie(_OAUTH_NEXT_COOKIE)
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, next: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "register.html",
        {"next": next, "oauth_providers": _enabled_oauth_providers()},
    )


@router.post("/register")
@rate_limit("5/minute")
async def register_endpoint(
    request: Request,
    bg: BackgroundTasks,
) -> Response:
    body = await parse_body(request)
    email = body.get("email", "")
    password = body.get("password", "")
    next = body.get("next", "")
    ip = request.client.host if request.client else None
    if not email or not password:
        if wants_json(request):
            return JSONResponse(
                {"detail": "Email and password are required."},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Email and password are required.", "email": email, "next": next},
            status_code=status.HTTP_400_BAD_REQUEST,
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
        audit(bg, "auth.register_failed", level="warning", ip=ip, email=email)
    except Exception:
        log.exception("auth.register_error", ip=ip, email=email)
        error = "An unexpected error occurred."
    if wants_json(request):
        return JSONResponse({"detail": error}, status_code=status.HTTP_400_BAD_REQUEST)
    return templates.TemplateResponse(
        request,
        "register.html",
        {"error": error, "email": email, "next": next},
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _set_impersonation_cookie(response: Response, name: str, value: str) -> None:
    response.set_cookie(
        name,
        value,
        httponly=True,
        secure=get_technical_settings().cookies_secure,
        samesite="lax",
        max_age=IMPERSONATION_MAX_SECONDS,
    )


@router.post("/impersonate")
async def impersonate_endpoint(
    request: Request,
    bg: BackgroundTasks,
    admin: CurrentAdmin,
    access_token: str | None = Cookie(default=None),
    refresh_token: str | None = Cookie(default=None),
) -> Response:
    body = await parse_body(request)
    email = str(body.get("email", "")).strip().lower()
    ip = request.client.host if request.client else None
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
    audit(
        bg,
        "auth.impersonation_started",
        level="warning",
        user_id=admin.id,
        ip=ip,
        target_email=email,
    )
    if wants_json(request):
        resp: Response = JSONResponse({"impersonating": email})
    else:
        resp = RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    # Stash the admin's own session, then become the target — everything time-boxed:
    # when these cookies expire the disguise and the stash die together.
    _set_impersonation_cookie(resp, IMPERSONATOR_COOKIE, access_token)
    _set_impersonation_cookie(resp, IMPERSONATOR_REFRESH_COOKIE, refresh_token or "")
    _set_impersonation_cookie(resp, "access_token", tokens.access_token)
    _set_impersonation_cookie(resp, "refresh_token", tokens.refresh_token)
    return resp


@router.post("/impersonate/stop")
async def stop_impersonation_endpoint(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
) -> Response:
    stash = request.cookies.get(IMPERSONATOR_COOKIE)
    refresh_stash = request.cookies.get(IMPERSONATOR_REFRESH_COOKIE, "")
    if not stash:
        return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)
    admin_id = None
    try:
        admin_id = decode_jwt(stash)["sub"]
    except Exception:  # expired stash: still drop the disguise, audit without the id
        log.warning("auth.impersonation_stash_invalid")
    audit(
        bg,
        "auth.impersonation_stopped",
        level="warning",
        user_id=admin_id,
        target_email=current_user.email,
    )
    if wants_json(request):
        resp: Response = JSONResponse({"impersonating": None})
    else:
        resp = RedirectResponse("/console", status_code=status.HTTP_303_SEE_OTHER)
    set_auth_cookies(resp, stash, refresh_stash)
    resp.delete_cookie(IMPERSONATOR_COOKIE)
    resp.delete_cookie(IMPERSONATOR_REFRESH_COOKIE)
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
        except Exception:
            log.exception("auth.password_reset_request_failed")
    if wants_json(request):
        return JSONResponse({"message": sent_message})
    return templates.TemplateResponse(request, "forgot_password.html", {"info": sent_message})


@router.post("/resend-confirmation")
@rate_limit("10/minute")
async def resend_confirmation_endpoint(request: Request, bg: BackgroundTasks) -> Response:
    """Send the signup confirmation again — the way out for an unconfirmed account.

    Neutral answer whatever happens (no account enumeration), like forgot-password.
    """
    if not settings.resend_confirmation_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    email = str(body.get("email", "")).strip().lower()
    sent_message = "If an account exists for this address, a confirmation email is on its way."
    if email:
        try:
            await resend_confirmation(email)
            audit(bg, "auth.confirmation_resent", email=email)
        except Exception:
            log.exception("auth.confirmation_resend_failed")
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
async def reset_password_endpoint(request: Request, bg: BackgroundTasks) -> Response:
    body = await parse_body(request)
    token_hash = str(body.get("token_hash", ""))
    password = str(body.get("password", ""))
    ip = request.client.host if request.client else None
    try:
        tokens = await confirm_signup(token_hash, type="recovery")
        await update_password(tokens.access_token, password)
    except PasswordUpdateError as e:
        # The recovery token is single-use and already consumed: a new link is needed.
        error = f"{e}. Please request a new reset link."
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=status.HTTP_400_BAD_REQUEST)
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception:
        log.exception("auth.password_reset_failed", ip=ip)
        error = "This reset link is invalid or has expired. Please request a new one."
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=status.HTTP_400_BAD_REQUEST)
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {"error": error},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    # The recovery session is dropped on purpose: the user signs in with the new password.
    audit(bg, "auth.password_reset", ip=ip)
    if wants_json(request):
        return JSONResponse({"message": _INFO_MESSAGES["password_reset"]})
    return RedirectResponse(
        "/auth/login?info=password_reset", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/confirm-email")
@rate_limit("10/minute")
async def confirm_email_endpoint(
    request: Request, bg: BackgroundTasks, token_hash: str = Query(default="")
) -> Response:
    """Finalize an email change from the link mailed to the new address.

    Anonymous on purpose — the single-use token IS the credential (the reader of
    the new mailbox proves ownership), and the requesting session may be gone.
    """
    try:
        tokens = await confirm_signup(token_hash, type="email_change")
    except Exception:
        log.exception("auth.email_change_failed", token_hash=token_hash[:8])
        return RedirectResponse(
            "/auth/login?info=email_change_failed", status_code=status.HTTP_303_SEE_OTHER
        )
    claims = decode_jwt(tokens.access_token)
    audit(bg, "auth.email_changed", user_id=str(claims.get("sub", "")))
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
        tokens = await confirm_signup(token_hash, type)
        await confirm_user(tokens.access_token)
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except Exception:
        log.exception("auth.confirm_error", token_hash=token_hash[:8])
        return RedirectResponse(
            "/auth/login?info=registered", status_code=status.HTTP_303_SEE_OTHER
        )
