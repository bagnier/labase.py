import structlog
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from app.auth.application import confirm_user, register_user
from app.auth.contract.current import OptionalCurrentUser
from app.auth.domain.service import confirm_signup, login, logout
from app.auth.infra.cookies import set_auth_cookies
from app.shared.http import parse_body, wants_json
from app.shared.http.limiter import rate_limit
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event

log = structlog.get_logger("labase.auth")

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
}


def _safe_next(next_url: str | None) -> str:
    """Return next_url if it is a safe internal path, else /profile."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/profile"


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
        request, "login.html", {"info": _INFO_MESSAGES.get(info or ""), "next": next}
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
        if wants_json(request):
            resp = JSONResponse({"access_token": tokens.access_token, "token_type": "bearer"})
            set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
            return resp
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except AuthApiError as e:
        record_audit_event(bg, level="warning", event="auth.login_failed", ip=ip, email=email)
        code = str(e.code) if e.code else ""
        error = _AUTH_ERROR_MESSAGES.get(code, "Invalid email or password")
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=status.HTTP_401_UNAUTHORIZED)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error, "email": email, "next": next},
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


@router.post("/logout")
async def logout_endpoint(access_token: str | None = Cookie(default=None)) -> Response:
    if access_token:
        await logout(access_token)
    resp = RedirectResponse("/auth/login", status_code=status.HTTP_303_SEE_OTHER)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, next: str | None = None) -> HTMLResponse:
    return templates.TemplateResponse(request, "register.html", {"next": next})


@router.post("/register")
@rate_limit("5/minute")
async def register_endpoint(
    request: Request,
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
