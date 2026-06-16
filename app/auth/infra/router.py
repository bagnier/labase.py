import structlog
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from app.auth.domain.service import AuthenticatedUser, login, logout
from app.auth.infra.cookies import set_auth_cookies
from app.auth.infra.security import try_get_current_user
from app.registration import register_user
from app.shared.http.limiter import rate_limit
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event
from app.shared.persistence.database import get_admin_session

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
    "registered": "Account created. Please verify your email before signing in.",
}


def _safe_next(next_url: str | None) -> str:
    """Return next_url if it is a safe internal path, else /profile."""
    if next_url and next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/profile"


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    info: str | None = None,
    next: str | None = None,
    current_user: AuthenticatedUser | None = Depends(try_get_current_user),
) -> Response:
    if current_user is not None:
        return RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        request, "login.html", {"info": _INFO_MESSAGES.get(info or ""), "next": next}
    )


@router.post("/login")
@rate_limit("10/minute")
async def login_endpoint(
    request: Request,
    bg: BackgroundTasks,
    email: str = Form(""),
    password: str = Form(""),
    next: str = Form(""),
) -> Response:
    ip = request.client.host if request.client else None
    if not email or not password:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Email and password are required.", "email": email, "next": next},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        tokens = await login(email, password)
        resp = RedirectResponse(_safe_next(next), status_code=status.HTTP_303_SEE_OTHER)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        return resp
    except AuthApiError as e:
        record_audit_event(bg, level="warning", event="auth.login_failed", ip=ip, email=email)
        code = str(e.code) if e.code else ""
        error = _AUTH_ERROR_MESSAGES.get(code, "Invalid email or password")
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": error, "email": email, "next": next},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception:
        log.exception("auth.login_error", ip=ip, email=email)
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
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "register.html")


@router.post("/register")
@rate_limit("5/minute")
async def register_endpoint(
    request: Request,
    bg: BackgroundTasks,
    email: str = Form(""),
    password: str = Form(""),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> Response:
    ip = request.client.host if request.client else None
    if not email or not password:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"error": "Email and password are required.", "email": email},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    try:
        await register_user(email, password, admin_session)
        return RedirectResponse(
            "/auth/login?info=registered", status_code=status.HTTP_303_SEE_OTHER
        )
    except AuthWeakPasswordError as e:
        error = f"Password too weak: {_format_weak_password_reasons(e.reasons)}"
    except AuthApiError as e:
        error = _friendly_auth_error(e)
        log.warning("auth.register_failed", ip=ip, email=email, code=str(e.code))
    except Exception:
        log.exception("auth.register_error", ip=ip, email=email)
        error = "An unexpected error occurred."
    return templates.TemplateResponse(
        request,
        "register.html",
        {"error": error, "email": email},
        status_code=status.HTTP_400_BAD_REQUEST,
    )
