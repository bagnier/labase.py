import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.organizations.infra.repository import OrganizationRepository
from app.profile.domain.models import ProfileCreate, ProfileUpdate
from app.profile.infra.context_processor import invalidate_display_name
from app.profile.infra.repository import ProfileRepository
from app.shared.dependencies import AdminSession, CurrentUser, RlsSession
from app.shared.http.templates import templates

router = APIRouter()


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    admin_session: AdminSession,
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    org_repo = OrganizationRepository(admin_session)
    pairs = await org_repo.list_with_role_for_user(uuid.UUID(current_user.id))
    orgs = [org for org, _ in pairs]
    org_slug = orgs[0].slug if orgs else ""
    org = orgs[0] if orgs else None
    return templates.TemplateResponse(
        request,
        "profile.html",
        {"user": current_user, "profile": profile, "orgs": orgs, "org_slug": org_slug, "org": org},
    )


@router.post("/profile", response_class=HTMLResponse)
async def profile_update(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    admin_session: AdminSession,
    display_name: str = Form(default=""),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    org_repo = OrganizationRepository(admin_session)
    pairs = await org_repo.list_with_role_for_user(uuid.UUID(current_user.id))
    orgs = [org for org, _ in pairs]
    org_slug = orgs[0].slug if orgs else ""
    org = orgs[0] if orgs else None
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    ctx: dict = {
        "user": current_user,
        "profile": profile,
        "orgs": orgs,
        "org_slug": org_slug,
        "org": org,
    }
    if display_name.strip() == "":
        ctx["error"] = "Display name cannot be empty."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    updated = await repo.update(profile, ProfileUpdate(display_name=display_name or None))
    invalidate_display_name(uuid.UUID(current_user.id))
    ctx["profile"] = updated
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
