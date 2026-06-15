import uuid

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.profile.contract.shell import shell_context
from app.profile.domain.models import ProfileCreate, ProfileUpdate
from app.profile.infra.repository import ProfileRepository
from app.shared.dependencies import CurrentUser, RlsSession
from app.shared.http.templates import templates
from app.shared.names import is_reserved, is_valid_handle

router = APIRouter()


async def _profile_context(session: RlsSession, current_user: CurrentUser) -> dict:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is not None and profile.handle is None:
        profile = await repo.auto_handle(profile, current_user.email)
    shell = await shell_context(session, current_user)
    orgs = shell["orgs"]
    return {
        "user": current_user,
        "profile": profile,
        "org_handle": orgs[0].handle if orgs else "",
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
    handle: str = Form(default=""),
) -> HTMLResponse:
    repo = ProfileRepository(session)
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    handle = handle.strip().lower()
    if not handle:
        ctx = await _profile_context(session, current_user)
        ctx["error"] = "Handle cannot be empty."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    if not is_valid_handle(handle):
        ctx = await _profile_context(session, current_user)
        ctx["error"] = "Handle must be lowercase alphanumeric with hyphens, max 39 chars."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    if is_reserved(handle):
        ctx = await _profile_context(session, current_user)
        ctx["error"] = f"'{handle}' is a reserved name."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=422)
    if not await repo.is_handle_available(handle, profile.id):
        ctx = await _profile_context(session, current_user)
        ctx["error"] = f"'{handle}' is already taken."
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=409)
    await repo.update(profile, ProfileUpdate(handle=handle))
    ctx = await _profile_context(session, current_user)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
