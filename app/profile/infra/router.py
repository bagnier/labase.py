import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.infra.session import get_rls_session
from app.auth.infra.security import get_current_user
from app.auth.domain.service import AuthenticatedUser
from app.organizations.infra.repository import OrganizationRepository
from app.profile.domain.models import ProfileUpdate
from app.profile.infra.repository import ProfileRepository
from app.shared.persistence.database import get_admin_session
from app.shared.http.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    admin_session: AsyncSession = Depends(get_admin_session),
) -> HTMLResponse:
    repo = OrganizationRepository(admin_session)
    pairs = await repo.list_with_role_for_user(uuid.UUID(current_user.id))
    orgs = [org for org, _ in pairs]
    org_slug = orgs[0].slug if orgs else ""
    return templates.TemplateResponse(
        request, "dashboard.html", {"user": current_user, "org_slug": org_slug, "orgs": orgs}
    )


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    return templates.TemplateResponse(
        request, "profile.html", {"user": current_user, "profile": profile}
    )


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    display_name: str = Form(default=""),
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    ctx: dict = {"user": current_user, "profile": profile}
    if profile is None:
        ctx["error"] = "Profil introuvable."
        return templates.TemplateResponse(request, "profile.html", ctx)
    if display_name.strip() == "":
        ctx["error"] = "Le nom d'affichage ne peut pas être vide."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    updated = await repo.update(profile, ProfileUpdate(display_name=display_name or None))
    ctx["profile"] = updated
    ctx["success"] = "Profil mis à jour."
    return templates.TemplateResponse(request, "profile.html", ctx)
