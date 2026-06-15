import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app.profile.contract.shell import shell_context
from app.profile.domain.models import ProfileCreate, ProfileRead, ProfileUpdate
from app.profile.infra.repository import ProfileRepository
from app.shared.dependencies import CurrentUser, RlsSession
from app.shared.http import wants_json
from app.shared.http.templates import templates
from app.shared.names import is_reserved, is_valid_handle

router = APIRouter()


async def _get_profile_repo(session: RlsSession) -> ProfileRepository:
    return ProfileRepository(session)


ProfileRepo = Annotated[ProfileRepository, Depends(_get_profile_repo)]


async def _profile_context(
    session: RlsSession, current_user: CurrentUser, repo: ProfileRepository
) -> dict:
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


@router.get("/profile", response_model=None)
async def profile_page(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    if wants_json(request):
        profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
        if profile is not None and profile.handle is None:
            profile = await repo.auto_handle(profile, current_user.email)
        if profile is None:
            return JSONResponse({"id": None, "handle": None, "email": current_user.email})
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(session, current_user, repo)
    return templates.TemplateResponse(request, "profile.html", ctx)


def _validate_handle(handle: str) -> tuple[int, str] | None:
    if not handle:
        return 422, "Handle cannot be empty."
    if not is_valid_handle(handle):
        return 422, "Handle must be lowercase alphanumeric with hyphens, max 39 chars."
    if is_reserved(handle):
        return 422, f"'{handle}' is a reserved name."
    return None


@router.post("/profile", response_model=None)
async def profile_update(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    handle: str = Form(default=""),
) -> HTMLResponse | JSONResponse:
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    handle = handle.strip().lower()

    error = _validate_handle(handle)
    if error is None and not await repo.is_handle_available(handle, profile.id):
        error = (409, f"'{handle}' is already taken.")

    if error is not None:
        status_code, message = error
        if wants_json(request):
            return JSONResponse({"detail": message}, status_code=status_code)
        ctx = await _profile_context(session, current_user, repo)
        ctx["error"] = message
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=status_code)

    await repo.update(profile, ProfileUpdate(handle=handle))
    if wants_json(request):
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(session, current_user, repo)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
