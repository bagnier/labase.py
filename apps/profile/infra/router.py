import asyncio
import base64
import json
import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.current import AuthenticatedUser, CurrentUser, RlsSession
from apps.auth.contract.deletion import disable_account
from apps.auth.contract.email_change import EmailChangeError, change_email
from apps.auth.contract.events import (
    EmailChangeRequested,
    PasskeyAdded,
    PasskeyRemoved,
    PasswordChanged,
    TwoFactorEnabled,
    UserDeleted,
)
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
from apps.auth.contract.settings import UsersSettings
from apps.auth.contract.two_factor import (
    TotpEnrollment,
    TotpError,
    enroll_totp,
    totp_challenge,
    verified_totp_factor,
    verify_totp,
)
from apps.organizations.contract.entity_links import entity_url
from apps.profile.contract.current import ProfileSettings
from apps.profile.contract.events import AccountDeleted, AvatarUpdated, HandleChanged
from apps.profile.domain.models import ProfileRead, ProfileUpdate
from apps.profile.infra.repository import ProfileRepository
from apps.shared import clock
from apps.shared.config import get_technical_settings
from apps.shared.events.bus import events
from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository import EventRepository
from apps.shared.events.timeline import (
    activity_entries,
    activity_stats,
    group_activity_by_day,
    heatmap_calendar,
)
from apps.shared.http import parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.storage import admin_storage, bucket
from apps.shared.settings import SettingsView, get_settings
from apps.shared.slug_registry import validate_handle

router = APIRouter()

_AVATAR_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AVATAR_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024

# The 2FA enrolment secret is generated once per POST and must survive the
# post/redirect/get to /profile — parked in a short-lived cookie (the MFA
# step-up / OAuth PKCE idiom) rather than re-rendered at the POST URL.
_ENROLLMENT_COOKIE = "twofa_enrollment"
_ENROLLMENT_MAX_SECONDS = 300

# Flash codes carried on the redirect back to GET /profile: a browser form POST
# lands on a real GET, so a reload never re-submits (JSON callers keep their
# inline message).
_PROFILE_FLASHES = {
    "password_changed": ("password_info", "Password changed."),
    "email_requested": ("email_info", "A confirmation email is on its way to your new address."),
    "avatar_updated": ("avatar_info", "Avatar updated."),
    "twofa_enabled": ("twofa_info", "Two-factor enabled."),
}


def _profile_redirect(flash: str | None = None) -> RedirectResponse:
    target = f"/profile?flash={flash}" if flash else "/profile"
    return RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)


def _encode_enrollment(enrollment: TotpEnrollment) -> str:
    payload = json.dumps(
        {
            "factor_id": enrollment.factor_id,
            "secret": enrollment.secret,
            "uri": enrollment.uri,
        }
    )
    return base64.urlsafe_b64encode(payload.encode()).decode()


def _decode_enrollment(raw: str) -> dict | None:
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except Exception:
        return None


async def _get_profile_repo(session: RlsSession) -> ProfileRepository:
    return ProfileRepository(session)


ProfileRepo = Annotated[ProfileRepository, Depends(_get_profile_repo)]


_ACTIVITY_PAGE = 25  # rows per activity view; "Load older" grows the window by this step
_ACTIVITY_MAX = 250  # a personal trail is bounded — cap the growable window


def _parse_dt(value: str | None) -> datetime | None:
    """A date/datetime from the toolbar's date inputs, or None when blank/unparseable."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _activity_query(q: str, app: str, from_dt: str, to_dt: str) -> str:
    """The current filter as a ``&``-prefixed querystring, to carry across a Load-older click."""
    raw = {"q": q, "app": app, "from_dt": from_dt, "to_dt": to_dt}
    params = {k: v for k, v in raw.items() if v}
    return f"&{urlencode(params)}" if params else ""


async def _activity_context(
    session: AsyncSession,
    user_id: uuid.UUID,
    handles: dict[uuid.UUID, str],
    *,
    q: str = "",
    app: str = "",
    from_dt: str = "",
    to_dt: str = "",
    limit: int = _ACTIVITY_PAGE,
) -> dict:
    """The day-grouped activity feed under the given filters — shared by the profile page's
    initial render and the ``/profile/activity`` HTMX fragment.

    Reads on the request's own RLS session: the ``business_events`` policy scopes rows to the
    reader (own actions + their orgs), so ``user_id`` narrows to the user's own trail. Each entry
    deep-links to the concerned entity, resolving the row's org to a handle from the user's own
    orgs (``handles``). ``who`` is dropped — every row is the viewer."""
    rows = await EventRepository(session).search(
        user_id=user_id,
        app=app or None,
        text=q or None,
        from_dt=_parse_dt(from_dt),
        to_dt=_parse_dt(to_dt),
        limit=limit,
    )

    def link(r: BusinessEventLog) -> str | None:
        return entity_url(r.kind, r.entity_id, handles.get(r.org_id))

    entries = activity_entries(rows, show_actor=False, link=link)
    return {
        "activity_groups": group_activity_by_day(entries, now=clock.now()),
        "activity_has_more": len(rows) >= limit and limit < _ACTIVITY_MAX,
        "activity_limit": limit,
        "activity_next_limit": min(limit + _ACTIVITY_PAGE, _ACTIVITY_MAX),
        "activity_q": q,
        "activity_app": app,
        "activity_from": from_dt,
        "activity_to": to_dt,
        "activity_query": _activity_query(q, app, from_dt, to_dt),
    }


async def _profile_context(
    request: Request, session: RlsSession, current_user: CurrentUser, repo: ProfileRepository
) -> dict:
    # Helper outside DI: profile routes carry no org, so the server view is the effective one.
    profile_settings = get_settings("profile").view()
    users_settings = get_settings("users").view()
    access_token = request.cookies.get("access_token", "")

    # The verified-factor lookup and the passkey list are two independent GoTrue round-trips
    # that gate only display state and touch neither the DB session nor each other. Fire them
    # up front so they overlap each other *and* the sequential DB work below, instead of
    # serializing three separate waits on the critical path of the site's busiest HTML page.
    two_factor_enabled = bool(users_settings.two_factor_enabled)
    passkeys_enabled = bool(users_settings.passkeys_enabled)
    twofa_task = (
        asyncio.ensure_future(verified_totp_factor(access_token))
        if two_factor_enabled and access_token
        else None
    )
    passkeys_task = (
        asyncio.ensure_future(list_passkeys(access_token))
        if passkeys_enabled and access_token
        else None
    )
    try:
        profile = await repo.get_with_auto_handle(
            current_user.id, current_user.email, profile_settings.handle_enabled
        )
        context = await fullpage_context(session, current_user)
        orgs = context["org_nav"]
        handles = {o.id: o.handle for o in orgs}
        counts = await EventRepository(session).daily_counts(user_id=current_user.id)
        activity = await _activity_context(session, current_user.id, handles)
    except BaseException:
        # Don't leave the in-flight GoTrue calls dangling if the DB work fails.
        for task in (twofa_task, passkeys_task):
            if task is not None:
                task.cancel()
        raise

    twofa_active = bool(twofa_task is not None and await twofa_task)
    passkeys: list[dict] = []
    if passkeys_task is not None:
        try:
            passkeys = await passkeys_task
        except PasskeyError:
            passkeys_enabled = False  # server-side feature off: hide the section
    now = clock.now()
    return {
        "user": current_user,
        "profile": profile,
        "org_handle": orgs[0].handle if orgs else "",
        "org": orgs[0] if orgs else None,
        "email_change_enabled": bool(profile_settings.email_change_enabled),
        "account_deletion_enabled": bool(profile_settings.account_deletion_enabled),
        "avatar_enabled": bool(profile_settings.avatar_enabled),
        "handle_enabled": bool(profile_settings.handle_enabled),
        "two_factor_enabled": two_factor_enabled,
        "twofa_active": twofa_active,
        "passkeys_enabled": passkeys_enabled,
        "passkeys": passkeys,
        "activity_calendar": heatmap_calendar(
            counts, now=now, since=profile.created_at if profile else None
        ),
        "activity_stats": activity_stats(counts, now=now),
        **activity,
        **context,
    }


async def _profile_error(
    request: Request,
    session: RlsSession,
    current_user: CurrentUser,
    repo: ProfileRepository,
    *,
    key: str,
    message: str,
    status_code: int = 400,
) -> HTMLResponse | JSONResponse:
    if wants_json(request):
        return JSONResponse({"detail": message}, status_code=status_code)
    ctx = await _profile_context(request, session, current_user, repo)
    ctx[key] = message
    return templates.TemplateResponse(request, "profile.html", ctx, status_code=status_code)


@router.get("/profile", response_model=None)
async def profile_page(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    if wants_json(request):
        profile = await repo.get_with_auto_handle(
            current_user.id, current_user.email, profile_settings.handle_enabled
        )
        if profile is None:
            return JSONResponse({"id": None, "handle": None, "email": current_user.email})
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(request, session, current_user, repo)
    flash = request.query_params.get("flash")
    if flash in _PROFILE_FLASHES:
        key, message = _PROFILE_FLASHES[flash]
        ctx[key] = message
    enrollment_raw = request.cookies.get(_ENROLLMENT_COOKIE)
    enrollment = _decode_enrollment(enrollment_raw) if enrollment_raw else None
    if enrollment:
        ctx["twofa_enrollment"] = enrollment
    response = templates.TemplateResponse(request, "profile.html", ctx)
    if enrollment_raw:
        # One-shot: the enrolment secret is shown once, then cleared.
        response.delete_cookie(_ENROLLMENT_COOKIE, path="/profile")
    return response


@router.get("/profile/activity", response_model=None)
async def profile_activity(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    q: str = "",
    app: str = "",
    from_dt: str = "",
    to_dt: str = "",
    limit: int = _ACTIVITY_PAGE,
) -> HTMLResponse | JSONResponse:
    """The day-grouped activity feed as an HTMX fragment — search, type filter, date range and
    Load-older all re-render it. API callers get the same trail as JSON."""
    limit = max(_ACTIVITY_PAGE, min(limit, _ACTIVITY_MAX))
    context = await fullpage_context(session, current_user)
    handles = {o.id: o.handle for o in context["org_nav"]}
    ctx = await _activity_context(
        session, current_user.id, handles, q=q, app=app, from_dt=from_dt, to_dt=to_dt, limit=limit
    )
    if wants_json(request):
        entries = [e for g in ctx["activity_groups"] for e in g["entries"]]
        return JSONResponse({"entries": [{**e, "ts": e["ts"].isoformat()} for e in entries]})
    return templates.TemplateResponse(request, "profile/activity_feed.html", ctx)


@router.post("/profile/password", response_model=None)
async def password_change(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> HTMLResponse | JSONResponse | RedirectResponse:
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
        return await _profile_error(
            request, session, current_user, repo, key="password_error", message=error
        )

    await events.emit(PasswordChanged(user_id=current_user.id))
    if wants_json(request):
        return JSONResponse({"message": "Password changed."})
    return _profile_redirect("password_changed")


@router.post("/profile/email", response_model=None)
async def email_change(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    if not profile_settings.email_change_enabled:
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
        return await _profile_error(
            request, session, current_user, repo, key="email_error", message=error
        )

    await events.emit(EmailChangeRequested(user_id=current_user.id, new_email=new_email))
    if wants_json(request):
        return JSONResponse({"message": f"A confirmation email is on its way to {new_email}."})
    return _profile_redirect("email_requested")


# ── Passkeys (WebAuthn) ─────────────────────────────────────────────────────────
# JSON-only: the profile page's JS drives navigator.credentials.create() between
# the two calls; deletion is a plain form for the no-JS path.


def _session_token(current_user: AuthenticatedUser) -> str:
    """The caller's live GoTrue token — the one `CurrentUser` resolved, refreshed included.

    A principal authenticated by an org API key holds no GoTrue session (`access_token` is empty),
    and GoTrue's user-scoped endpoints below are meaningless for it: these surfaces answer 404, as
    they do when the feature is switched off."""
    if not current_user.access_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return current_user.access_token


def _ensure_passkeys(users_settings: SettingsView, current_user: AuthenticatedUser) -> str:
    if not users_settings.passkeys_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _session_token(current_user)


def _ensure_two_factor(users_settings: SettingsView, current_user: AuthenticatedUser) -> str:
    if not users_settings.two_factor_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _session_token(current_user)


@router.post("/profile/passkeys/options", response_model=None)
async def passkey_options(
    current_user: CurrentUser,
    users_settings: UsersSettings,
) -> JSONResponse:
    access_token = _ensure_passkeys(users_settings, current_user)
    try:
        return JSONResponse(await passkey_registration_options(access_token))
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.post("/profile/passkeys/verify", response_model=None)
async def passkey_verify(
    request: Request,
    current_user: CurrentUser,
    users_settings: UsersSettings,
) -> JSONResponse:
    access_token = _ensure_passkeys(users_settings, current_user)
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
    await events.emit(PasskeyAdded(user_id=current_user.id))
    return JSONResponse({"message": "Passkey added.", "passkey": created})


@router.post("/profile/passkeys/{passkey_id}/delete", response_model=None)
async def passkey_delete(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> HTMLResponse | JSONResponse | Response:
    access_token = _ensure_passkeys(users_settings, current_user)
    try:
        await delete_passkey(access_token, str(passkey_id))
    except PasskeyError as e:
        return await _profile_error(
            request, session, current_user, repo, key="passkey_error", message=str(e)
        )
    await events.emit(PasskeyRemoved(user_id=current_user.id, entity_id=passkey_id))
    if wants_json(request):
        return JSONResponse({"message": "Passkey removed."})
    return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/2fa/enroll", response_model=None)
async def twofa_enroll(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    access_token = _ensure_two_factor(users_settings, current_user)
    try:
        enrollment = await enroll_totp(access_token)
    except TotpError as e:
        return await _profile_error(
            request, session, current_user, repo, key="twofa_error", message=str(e)
        )
    if wants_json(request):
        return JSONResponse(
            {
                "factor_id": enrollment.factor_id,
                "secret": enrollment.secret,
                "uri": enrollment.uri,
            }
        )
    response = _profile_redirect()
    response.set_cookie(
        _ENROLLMENT_COOKIE,
        _encode_enrollment(enrollment),
        max_age=_ENROLLMENT_MAX_SECONDS,
        httponly=True,
        secure=get_technical_settings().cookies_secure,
        samesite="lax",
        path="/profile",
    )
    return response


@router.post("/profile/2fa/verify", response_model=None)
async def twofa_verify(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    access_token = _ensure_two_factor(users_settings, current_user)
    body = await parse_body(request)
    factor_id = str(body.get("factor_id", ""))
    code = str(body.get("code", "")).strip()
    try:
        challenge_id = await totp_challenge(access_token, factor_id)
        await verify_totp(access_token, factor_id, challenge_id, code)
    except TotpError:
        error = "That code did not work. Try the next one from your app."
        return await _profile_error(
            request, session, current_user, repo, key="twofa_error", message=error
        )
    await events.emit(TwoFactorEnabled(user_id=current_user.id))
    if wants_json(request):
        return JSONResponse({"message": "Two-factor enabled."})
    return _profile_redirect("twofa_enabled")


@router.delete("/profile", response_model=None)
@router.post("/profile/delete", response_model=None)
async def account_delete(
    request: Request,
    current_user: CurrentUser,
    admin_session: AdminSession,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
    if not profile_settings.account_deletion_enabled:
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
        return await _profile_error(
            request, session, current_user, repo, key="deletion_error", message=error
        )

    await events.emit(AccountDeleted(user_id=current_user.id, entity_id=current_user.id))
    # The UserDeleted fact rides the admin session — it commits iff the deletion does. Its forget
    # consumers (organizations, profile) then run asynchronously off the tailer, by user id.
    await events.emit(
        UserDeleted(user_id=current_user.id, entity_id=current_user.id), session=admin_session
    )
    # GoTrue last, before commit: if closing access fails, nothing is deleted.
    await disable_account(str(current_user.id))
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
    file: UploadFile,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    if not profile_settings.avatar_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    ext = _AVATAR_EXT.get(file.content_type or "")
    content = await file.read()
    error: str | None = None
    if ext is None or not content or len(content) > _AVATAR_MAX_BYTES:
        error = "Avatars must be a PNG, JPEG or WebP image (max 2 MB)."

    if error is not None:
        return await _profile_error(
            request, session, current_user, repo, key="avatar_error", message=error
        )

    path = f"avatars/{current_user.id}.{ext}"
    await (
        admin_storage()
        .from_(bucket())
        .upload(path, content, {"content-type": file.content_type or "", "x-upsert": "true"})
    )
    profile = await repo.get_or_create(current_user.id, current_user.email)
    profile.avatar_path = path
    await session.flush()
    await events.emit(AvatarUpdated(user_id=current_user.id))
    if wants_json(request):
        return JSONResponse({"message": "Avatar updated."})
    return _profile_redirect("avatar_updated")


@router.get("/profile/avatar/{auth_user_id}", response_model=None)
async def avatar_image(
    auth_user_id: uuid.UUID,
    current_user: CurrentUser,
    admin_session: AdminSession,
    profile_settings: ProfileSettings,
) -> Response:
    """Streams the avatar to any signed-in user (they appear next to members)."""
    if not profile_settings.avatar_enabled:
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
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> HTMLResponse | JSONResponse | RedirectResponse:
    if not profile_settings.handle_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    body = await parse_body(request)
    handle = str(body.get("handle", ""))
    profile = await repo.get_or_create(current_user.id, current_user.email)
    handle = handle.strip().lower()

    error = validate_handle(handle)
    if error is None and not await repo.is_handle_available(handle, profile.id):
        error = (409, f"'{handle}' is already taken.")

    if error is not None:
        status_code, message = error
        return await _profile_error(
            request,
            session,
            current_user,
            repo,
            key="error",
            message=message,
            status_code=status_code,
        )

    old_handle = profile.handle
    await repo.update(profile, ProfileUpdate(handle=handle))
    if old_handle != handle:
        await events.emit(HandleChanged(user_id=current_user.id, new_handle=handle))
    if wants_json(request):
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
