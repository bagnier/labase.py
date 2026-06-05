import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from supabase_auth import User

from app.auth.infra.dependencies import get_current_user
from app.profile.domain.models import ProfileUpdate
from app.profile.infra.repository import ProfileRepository
from app.shared.database import get_session
from app.shared.templates import templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "home.html")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> HTMLResponse:
    return templates.TemplateResponse(request, "dashboard.html", {"user": current_user})


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
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
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    ctx: dict = {"user": current_user, "profile": profile}
    if profile is None:
        ctx["error"] = "Profil introuvable."
        return templates.TemplateResponse(request, "profile.html", ctx)
    updated = await repo.update(profile, ProfileUpdate(display_name=display_name or None))
    ctx["profile"] = updated
    ctx["success"] = "Profil mis à jour."
    return templates.TemplateResponse(request, "profile.html", ctx)
