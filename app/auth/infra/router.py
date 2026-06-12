import structlog
from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Form, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession
from supabase_auth.errors import AuthApiError, AuthWeakPasswordError

from app.auth.domain.service import login, logout
from app.auth.infra.cookies import set_auth_cookies
from app.shared.http.limiter import rate_limit
from app.shared.http.templates import templates
from app.shared.observability.audit import record_audit_event
from app.shared.persistence.database import get_admin_session
from app.shared.registration import register_user

log = structlog.get_logger("labase.auth")

router = APIRouter()

_WEAK_PASSWORD_REASONS: dict[str, str] = {
    "too_short": "trop court",
    "too_simple": "trop simple",
    "no_uppercase": "doit contenir une majuscule",
    "no_lowercase": "doit contenir une minuscule",
    "no_digit": "doit contenir un chiffre",
    "no_special": "doit contenir un caractère spécial",
    "pwned": "ce mot de passe est compromis",
}

_AUTH_ERROR_MESSAGES: dict[str, str] = {
    "email_exists": "Un compte existe déjà avec cet email.",
    "user_already_exists": "Un compte existe déjà avec cet email.",
    "email_address_not_authorized": "Cette adresse email n'est pas autorisée.",
    "signup_disabled": "Les inscriptions sont désactivées.",
    "invalid_email": "Adresse email invalide.",
}


def _format_weak_password_reasons(reasons: list[str]) -> str:
    labels = [_WEAK_PASSWORD_REASONS.get(r, r) for r in reasons]
    return ", ".join(labels) if labels else "critères non respectés"


def _friendly_auth_error(e: AuthApiError) -> str:
    code = str(e.code) if e.code else ""
    return _AUTH_ERROR_MESSAGES.get(code, e.message)


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "login.html")


@router.post("/login")
@rate_limit("10/minute")
async def login_endpoint(
    request: Request,
    bg: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    ip = request.client.host if request.client else None
    try:
        tokens = await login(email, password)
        resp = Response(status_code=status.HTTP_200_OK)
        set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        resp.headers["HX-Redirect"] = "/profile"
        return resp
    except Exception:
        record_audit_event(bg, level="warning", event="auth.login_failed", ip=ip, email=email)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Email ou mot de passe invalide"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@router.post("/logout")
async def logout_endpoint(access_token: str | None = Cookie(default=None)) -> Response:
    if access_token:
        await logout(access_token)
    resp = Response(status_code=status.HTTP_200_OK)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    resp.headers["HX-Redirect"] = "/auth/login"
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "register.html")


@router.post("/register")
@rate_limit("5/minute")
async def register_endpoint(
    request: Request,
    bg: BackgroundTasks,
    email: str = Form(...),
    password: str = Form(...),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> Response:
    ip = request.client.host if request.client else None
    try:
        await register_user(email, password, admin_session)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"info": "Compte créé. Vérifiez votre email puis connectez-vous."},
        )
    except AuthWeakPasswordError as e:
        error = f"Mot de passe trop faible : {_format_weak_password_reasons(e.reasons)}"
    except AuthApiError as e:
        error = _friendly_auth_error(e)
        log.warning("auth.register_failed", ip=ip, email=email, code=str(e.code))
    except Exception:
        log.exception("auth.register_error", ip=ip, email=email)
        error = "Une erreur inattendue s'est produite."
    return templates.TemplateResponse(
        request,
        "register.html",
        {"error": error},
        status_code=status.HTTP_400_BAD_REQUEST,
    )
