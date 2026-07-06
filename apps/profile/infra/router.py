import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse

from apps.auth.contract.current import CurrentUser, RlsSession
from apps.auth.contract.email_change import EmailChangeError, change_email
from apps.auth.contract.passwords import PasswordUpdateError, WrongPassword, change_password
from apps.profile.contract import settings
from apps.profile.domain.models import ProfileCreate, ProfileRead, ProfileUpdate
from apps.profile.infra.repository import ProfileRepository
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.slug_registry import validate_handle

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
    context = await fullpage_context(session, current_user)
    orgs = context["org_nav"]
    return {
        "user": current_user,
        "profile": profile,
        "org_handle": orgs[0].handle if orgs else "",
        "org": orgs[0] if orgs else None,
        "email_change_enabled": bool(settings.email_change_enabled),
        **context,
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


@router.post("/profile/password", response_model=None)
async def password_change(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    body = await parse_body(request)
    current_password = str(body.get("current_password", ""))
    new_password = str(body.get("new_password", ""))
    error: str | None = None
    if not current_password or not new_password:
        error = "Current and new password are required."
    else:
        try:
            await change_password(current_user.email, current_password, new_password)
        except WrongPassword:
            error = "Current password is incorrect."
        except PasswordUpdateError as e:
            error = str(e)

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(session, current_user, repo)
        ctx["password_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    audit(bg, "profile.password_changed", user_id=current_user.id)
    if wants_json(request):
        return JSONResponse({"message": "Password changed."})
    ctx = await _profile_context(session, current_user, repo)
    ctx["password_info"] = "Password changed."
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.post("/profile/email", response_model=None)
async def email_change(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    if not settings.email_change_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    new_email = str(body.get("new_email", "")).strip().lower()
    current_password = str(body.get("current_password", ""))
    error: str | None = None
    if not new_email or not current_password:
        error = "New email and current password are required."
    else:
        try:
            await change_email(current_user.email, current_password, new_email)
        except WrongPassword:
            error = "Current password is incorrect."
        except EmailChangeError as e:
            error = str(e)

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(session, current_user, repo)
        ctx["email_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    audit(bg, "profile.email_change_requested", user_id=current_user.id, new_email=new_email)
    info = f"A confirmation email is on its way to {new_email}."
    if wants_json(request):
        return JSONResponse({"message": info})
    ctx = await _profile_context(session, current_user, repo)
    ctx["email_info"] = info
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.post("/profile", response_model=None)
async def profile_update(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    body = await parse_body(request)
    handle = str(body.get("handle", ""))
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    handle = handle.strip().lower()

    error = validate_handle(handle)
    if error is None and not await repo.is_handle_available(handle, profile.id):
        error = (409, f"'{handle}' is already taken.")

    if error is not None:
        status_code, message = error
        if wants_json(request):
            return JSONResponse({"detail": message}, status_code=status_code)
        ctx = await _profile_context(session, current_user, repo)
        ctx["error"] = message
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=status_code)

    old_handle = profile.handle
    await repo.update(profile, ProfileUpdate(handle=handle))
    if old_handle != handle:
        audit(
            bg,
            "profile.handle_changed",
            user_id=current_user.id,
            new_handle=handle,
        )
    if wants_json(request):
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(session, current_user, repo)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
