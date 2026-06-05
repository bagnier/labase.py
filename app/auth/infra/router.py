from pathlib import Path

from fastapi import APIRouter, Form, Request, Response, status
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.auth.domain.service import login, logout, register

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent.parent / "templates"))

_COOKIE_MAX_AGE = 60 * 60 * 24 * 7


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    response.set_cookie(
        "access_token", access_token,
        httponly=True, secure=True, samesite="lax", max_age=_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, secure=True, samesite="lax", max_age=_COOKIE_MAX_AGE,
    )


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/login.html")


@router.post("/login")
async def login_endpoint(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        tokens = login(email, password)
        resp = Response(status_code=status.HTTP_200_OK)
        _set_auth_cookies(resp, tokens.access_token, tokens.refresh_token)
        resp.headers["HX-Redirect"] = "/dashboard"
        return resp
    except Exception:
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"error": "Email ou mot de passe invalide"},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


@router.post("/logout")
async def logout_endpoint() -> Response:
    logout()
    resp = Response(status_code=status.HTTP_200_OK)
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    resp.headers["HX-Redirect"] = "/auth/login"
    return resp


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "auth/register.html")


@router.post("/register")
async def register_endpoint(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
) -> Response:
    try:
        register(email, password)
        return templates.TemplateResponse(
            request,
            "auth/login.html",
            {"info": "Compte créé. Vérifiez votre email puis connectez-vous."},
        )
    except Exception as e:
        return templates.TemplateResponse(
            request,
            "auth/register.html",
            {"error": str(e)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
