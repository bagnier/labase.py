from pathlib import Path

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware

from app.auth.infra.router import router as auth_router
from app.files.infra.router import public_router as files_public_router
from app.files.infra.router import router as files_router
from app.health.router import router as health_router
from app.organizations.infra.html_router import router as organizations_html_router
from app.organizations.infra.invitation_router import router as invitations_router
from app.organizations.infra.router import router as organizations_router
from app.profile.infra.router import router as profile_router
from app.shared.config import get_settings
from app.shared.limiter import limiter
from app.shared.logging import setup_logging
from app.shared.middleware_logging import LoggingMiddleware
from app.todo.infra.router import router as todo_router

setup_logging()
log = structlog.get_logger("labase.app")

BASE_DIR = Path(__file__).parent

_settings = get_settings()

app = FastAPI(title="labase")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: Exception) -> Response:
    return JSONResponse({"detail": "Too many requests"}, status_code=429)


app.add_middleware(LoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = _CSP
    return response


@app.exception_handler(500)
async def unhandled_exception_handler(request: Request, exc: Exception) -> Response:
    log.exception(
        "request.unhandled_error",
        method=request.method,
        path=request.url.path,
    )
    return JSONResponse({"detail": "Internal server error"}, status_code=500)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    if exc.status_code == 401:
        if request.headers.get("HX-Request"):
            r = Response(status_code=200)
            r.headers["HX-Redirect"] = "/auth/login"
            return r
        if "text/html" in request.headers.get("Accept", ""):
            return RedirectResponse(url="/auth/login", status_code=302)
    return JSONResponse(
        {"detail": exc.detail}, status_code=exc.status_code, headers=dict(exc.headers or {})
    )


app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")

app.include_router(health_router)
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(organizations_router)
app.include_router(invitations_router)
app.include_router(profile_router, tags=["profile"])

# Public share endpoint — mounted before org-scoped routes to avoid slug conflicts
app.include_router(files_public_router)

# Org-scoped routes: /orgs/{org_slug}/...
app.include_router(organizations_html_router, prefix="/orgs/{org_slug}")
app.include_router(files_router, prefix="/orgs/{org_slug}")
app.include_router(todo_router, prefix="/orgs/{org_slug}")
