from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.auth.infra.router import router as auth_router
from app.files.infra.router import public_router as files_public_router
from app.files.infra.router import router as files_router
from app.organizations.infra.html_router import router as organizations_html_router
from app.organizations.infra.invitation_router import router as invitations_router
from app.organizations.infra.router import router as organizations_router
from app.profile.infra.router import router as profile_router
from app.todo.infra.router import router as todo_router

BASE_DIR = Path(__file__).parent

app = FastAPI(title="labase")

app.mount("/static", StaticFiles(directory=str(BASE_DIR.parent / "static")), name="static")

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
