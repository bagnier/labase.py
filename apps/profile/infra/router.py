import uuid
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Cookie,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.auth.contract import settings as users_settings
from apps.auth.contract.current import CurrentUser, RlsSession
from apps.auth.contract.deletion import disable_account
from apps.auth.contract.email_change import EmailChangeError, change_email
from apps.auth.contract.events import UserDeleted
from apps.auth.contract.passkeys import (
    PasskeyError,
    delete_passkey,
    list_passkeys,
    passkey_registration_options,
    verify_passkey_registration,
)
from apps.auth.contract.passwords import (
    PasswordUpdateError,
    WrongPassword,
    change_password,
    verify_password,
)
from apps.auth.contract.two_factor import (
    TotpError,
    enroll_totp,
    totp_challenge,
    verified_totp_factor,
    verify_totp,
)
from apps.profile.contract import settings
from apps.profile.domain.models import ProfileCreate, ProfileRead, ProfileUpdate
from apps.profile.infra.repository import ProfileRepository
from apps.shared.host import host
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.storage import admin_storage, bucket
from apps.shared.slug_registry import validate_handle

router = APIRouter()

_AVATAR_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AVATAR_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024


async def _get_profile_repo(session: RlsSession) -> ProfileRepository:
    return ProfileRepository(session)


ProfileRepo = Annotated[ProfileRepository, Depends(_get_profile_repo)]


async def _profile_context(
    request: Request, session: RlsSession, current_user: CurrentUser, repo: ProfileRepository
) -> dict:
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is not None and profile.handle is None and settings.handle_enabled:
        profile = await repo.auto_handle(profile, current_user.email)
    two_factor_enabled = bool(users_settings.two_factor_enabled)
    access_token = request.cookies.get("access_token", "")
    twofa_active = bool(
        two_factor_enabled and access_token and await verified_totp_factor(access_token)
    )
    passkeys_enabled = bool(users_settings.passkeys_enabled)
    passkeys: list[dict] = []
    if passkeys_enabled and access_token:
        try:
            passkeys = await list_passkeys(access_token)
        except PasskeyError:
            passkeys_enabled = False  # server-side feature off: hide the section
    context = await fullpage_context(session, current_user)
    orgs = context["org_nav"]
    return {
        "user": current_user,
        "profile": profile,
        "org_handle": orgs[0].handle if orgs else "",
        "org": orgs[0] if orgs else None,
        "email_change_enabled": bool(settings.email_change_enabled),
        "account_deletion_enabled": bool(settings.account_deletion_enabled),
        "avatar_enabled": bool(settings.avatar_enabled),
        "handle_enabled": bool(settings.handle_enabled),
        "two_factor_enabled": two_factor_enabled,
        "twofa_active": twofa_active,
        "passkeys_enabled": passkeys_enabled,
        "passkeys": passkeys,
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
        if profile is not None and profile.handle is None and settings.handle_enabled:
            profile = await repo.auto_handle(profile, current_user.email)
        if profile is None:
            return JSONResponse({"id": None, "handle": None, "email": current_user.email})
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(request, session, current_user, repo)
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
            access_token = request.cookies.get("access_token", "")
            await change_password(current_user.email, current_password, new_password, access_token)
        except WrongPassword:
            error = "Current password is incorrect."
        except PasswordUpdateError as e:
            error = str(e)

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["password_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    audit(bg, "profile.password_changed", user_id=current_user.id)
    if wants_json(request):
        return JSONResponse({"message": "Password changed."})
    ctx = await _profile_context(request, session, current_user, repo)
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
            access_token = request.cookies.get("access_token", "")
            await change_email(current_user.email, current_password, new_email, access_token)
        except WrongPassword:
            error = "Current password is incorrect."
        except EmailChangeError as e:
            error = str(e)

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["email_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    audit(bg, "profile.email_change_requested", user_id=current_user.id, new_email=new_email)
    info = f"A confirmation email is on its way to {new_email}."
    if wants_json(request):
        return JSONResponse({"message": info})
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["email_info"] = info
    return templates.TemplateResponse(request, "profile.html", ctx)


# ── Passkeys (WebAuthn) ─────────────────────────────────────────────────────────
# JSON-only: the profile page's JS drives navigator.credentials.create() between
# the two calls; deletion is a plain form for the no-JS path.


def _ensure_passkeys(access_token: str | None) -> None:
    if not users_settings.passkeys_enabled or not access_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/profile/passkeys/options", response_model=None)
async def passkey_options(
    current_user: CurrentUser,
    access_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _ensure_passkeys(access_token)
    assert access_token is not None
    try:
        return JSONResponse(await passkey_registration_options(access_token))
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.post("/profile/passkeys/verify", response_model=None)
async def passkey_verify(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    access_token: str | None = Cookie(default=None),
) -> JSONResponse:
    _ensure_passkeys(access_token)
    assert access_token is not None
    body = await parse_body(request)
    challenge_id = str(body.get("challenge_id", ""))
    credential = body.get("credential")
    if not challenge_id or not isinstance(credential, dict):
        return JSONResponse(
            {"detail": "challenge_id and credential are required."}, status_code=400
        )
    try:
        created = await verify_passkey_registration(access_token, challenge_id, credential)
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    audit(bg, "profile.passkey_added", user_id=current_user.id)
    return JSONResponse({"message": "Passkey added.", "passkey": created})


@router.post("/profile/passkeys/{passkey_id}/delete", response_model=None)
async def passkey_delete(
    request: Request,
    bg: BackgroundTasks,
    passkey_id: str,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    access_token: str | None = Cookie(default=None),
) -> HTMLResponse | JSONResponse | Response:
    _ensure_passkeys(access_token)
    assert access_token is not None
    try:
        await delete_passkey(access_token, passkey_id)
    except PasskeyError as e:
        if wants_json(request):
            return JSONResponse({"detail": str(e)}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["passkey_error"] = str(e)
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)
    audit(bg, "profile.passkey_removed", user_id=current_user.id, passkey_id=passkey_id)
    if wants_json(request):
        return JSONResponse({"message": "Passkey removed."})
    return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/2fa/enroll", response_model=None)
async def twofa_enroll(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    access_token: str | None = Cookie(default=None),
) -> HTMLResponse | JSONResponse:
    if not users_settings.two_factor_enabled or not access_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    try:
        enrollment = await enroll_totp(access_token)
    except TotpError as e:
        if wants_json(request):
            return JSONResponse({"detail": str(e)}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["twofa_error"] = str(e)
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)
    if wants_json(request):
        return JSONResponse(
            {
                "factor_id": enrollment.factor_id,
                "secret": enrollment.secret,
                "uri": enrollment.uri,
            }
        )
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["twofa_enrollment"] = enrollment
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.post("/profile/2fa/verify", response_model=None)
async def twofa_verify(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    access_token: str | None = Cookie(default=None),
) -> HTMLResponse | JSONResponse:
    if not users_settings.two_factor_enabled or not access_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    factor_id = str(body.get("factor_id", ""))
    code = str(body.get("code", "")).strip()
    try:
        challenge_id = await totp_challenge(access_token, factor_id)
        await verify_totp(access_token, factor_id, challenge_id, code)
    except TotpError:
        error = "That code did not work. Try the next one from your app."
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["twofa_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)
    audit(bg, "profile.twofa_enabled", user_id=current_user.id)
    if wants_json(request):
        return JSONResponse({"message": "Two-factor enabled."})
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["twofa_active"] = True
    ctx["twofa_info"] = "Two-factor enabled."
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.delete("/profile", response_model=None)
@router.post("/profile/delete", response_model=None)
async def account_delete(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    admin_session: AdminSession,
    session: RlsSession,
    repo: ProfileRepo,
) -> Response:
    if not settings.account_deletion_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    current_password = str(body.get("current_password", ""))
    error: str | None = None
    if not current_password:
        error = "Your password is required."
    else:
        try:
            await verify_password(current_user.email, current_password)
        except WrongPassword:
            error = "Current password is incorrect."

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["deletion_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    audit(bg, "profile.account_deleted", level="warning", user_id=current_user.id)
    # Handlers (organizations, profile itself…) join the admin session: one
    # transaction for the whole deletion.
    await host.events.emit(UserDeleted(user_id=current_user.id, session=admin_session))
    # GoTrue last, before commit: if closing access fails, nothing is deleted.
    await disable_account(current_user.id)
    await admin_session.commit()
    if wants_json(request):
        resp: Response = JSONResponse({"message": "Account deleted."})
    else:
        resp = RedirectResponse(
            "/auth/login?info=account_deleted", status_code=status.HTTP_303_SEE_OTHER
        )
    resp.delete_cookie("access_token")
    resp.delete_cookie("refresh_token")
    return resp


@router.post("/profile/avatar", response_model=None)
async def avatar_upload(
    request: Request,
    bg: BackgroundTasks,
    file: UploadFile,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    if not settings.avatar_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ext = _AVATAR_EXT.get(file.content_type or "")
    content = await file.read()
    error: str | None = None
    if ext is None or not content or len(content) > _AVATAR_MAX_BYTES:
        error = "Avatars must be a PNG, JPEG or WebP image (max 2 MB)."

    if error is not None:
        if wants_json(request):
            return JSONResponse({"detail": error}, status_code=400)
        ctx = await _profile_context(request, session, current_user, repo)
        ctx["avatar_error"] = error
        return templates.TemplateResponse(request, "profile.html", ctx, status_code=400)

    path = f"avatars/{current_user.id}.{ext}"
    await (
        admin_storage()
        .from_(bucket())
        .upload(path, content, {"content-type": file.content_type or "", "x-upsert": "true"})
    )
    profile = await repo.get_by_auth_user_id(uuid.UUID(current_user.id))
    if profile is None:
        profile = await repo.create(
            ProfileCreate(auth_user_id=uuid.UUID(current_user.id), email=current_user.email)
        )
    profile.avatar_path = path
    await session.flush()
    audit(bg, "profile.avatar_updated", user_id=current_user.id)
    if wants_json(request):
        return JSONResponse({"message": "Avatar updated."})
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["avatar_info"] = "Avatar updated."
    return templates.TemplateResponse(request, "profile.html", ctx)


@router.get("/profile/avatar/{auth_user_id}", response_model=None)
async def avatar_image(
    auth_user_id: uuid.UUID, current_user: CurrentUser, admin_session: AdminSession
) -> Response:
    """Streams the avatar to any signed-in user (they appear next to members)."""
    if not settings.avatar_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    profile = await ProfileRepository(admin_session).get_by_auth_user_id(auth_user_id)
    if profile is None or not profile.avatar_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    content = await admin_storage().from_(bucket()).download(profile.avatar_path)
    media_type = _AVATAR_MEDIA.get(profile.avatar_path.rsplit(".", 1)[-1], "image/png")
    return Response(
        content, media_type=media_type, headers={"Cache-Control": "private, max-age=300"}
    )


@router.post("/profile", response_model=None)
async def profile_update(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse:
    if not settings.handle_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
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
        ctx = await _profile_context(request, session, current_user, repo)
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
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
