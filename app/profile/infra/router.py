import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.profile.contract.shell import shell_context
from app.profile.domain.models import ProfileCreate, ProfileUpdate
from app.profile.infra.repository import ProfileRepository
from app.shared.dependencies import CurrentUser, RlsSession
from app.shared.http.templates import templates

router = APIRouter()


async def _profile_context(session: RlsSession, current_user: CurrentUser) -> dict:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    shell = await shell_context(session, current_user)
    orgs = shell["orgs"]
    return {
        "user": current_user,
        "profile": profile,
        "org_slug": orgs[0].slug if orgs else "",
        "org": orgs[0] if orgs else None,
        **shell,
    }


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
) -> HTMLResponse:
    ctx = await _profile_context(session, current_user)
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    display_name: str = Form(default=""),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    if display_name.strip() == "":
        ctx = await _profile_context(session, current_user)
        ctx["error"] = "Display name cannot be empty."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    await repo.update(profile, ProfileUpdate(display_name=display_name or None))
    ctx = await _profile_context(session, current_user)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
