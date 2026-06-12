from pathlib import Path

from fastapi import FastAPI, HTTPException
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
from app.shared.http.exceptions import handle_http_error, handle_rate_limit, handle_unhandled_error
from app.shared.http.limiter import limiter
from app.shared.http.security import cors_config, security_headers
from app.shared.observability.logging import setup_logging
from app.shared.observability.request import RequestLogger
from app.todo.infra.router import router as todo_router

setup_logging()

BASE_DIR = Path(__file__).parent
_settings = get_settings()

app = FastAPI(title="labase")
app.state.limiter = limiter

app.exception_handler(RateLimitExceeded)(handle_rate_limit)
app.exception_handler(500)(handle_unhandled_error)
app.exception_handler(HTTPException)(handle_http_error)

app.middleware("http")(security_headers)
app.add_middleware(RequestLogger)
app.add_middleware(CORSMiddleware, **cors_config(_settings.cors_origins))

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
