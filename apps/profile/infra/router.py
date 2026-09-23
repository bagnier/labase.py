import asyncio
import base64
import json
import uuid
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlencode

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.admin import (
    LastAdminViolation,
    ensure_not_last_admin,
    list_server_admins,
    lock_last_admin_guard,
)
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
    set_auth_cookies,
    totp_challenge,
    verified_totp_factor,
    verify_totp,
)
from apps.organizations.contract.entity_links import entity_url
from apps.profile.contract.current import ProfileSettings
from apps.profile.contract.events import AccountDeleted, AvatarUpdated, HandleChanged
from apps.profile.domain.models import (
    AccountDeletion,
    EmailChange,
    HandleUpdate,
    PasskeyRegistered,
    PasskeyRegistration,
    PasswordChange,
    ProfileRead,
    ProfileStub,
    ProfileUpdate,
    TotpEnrolmentCheck,
    TotpEnrolmentRead,
)
from apps.profile.infra.repository import ProfileRepository
from apps.shared import clock
from apps.shared.dto import Message
from apps.shared.events.activity import (
    ActivityFeedRead,
    activity_entries,
    activity_stats,
    group_activity_by_day,
    heatmap_calendar,
)
from apps.shared.events.bus import events
from apps.shared.events.models import BusinessEventRecord
from apps.shared.events.repository import EventRepository
from apps.shared.http import json_and_html, wants_json
from apps.shared.http.templates import templates
from apps.shared.integration.fullpage import fullpage_context
from apps.shared.integration.slugs import validate_handle
from apps.shared.logs.dependency import log_dependency_failure
from apps.shared.persistence.database import AdminSession
from apps.shared.persistence.storage import admin_storage, bucket
from apps.shared.settings.env import get_technical_settings
from apps.shared.settings.live import SettingsView, get_settings

log = structlog.get_logger(__name__)

router = APIRouter()

_AVATAR_EXT = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AVATAR_MEDIA = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024

# Where the 2FA enrolment secret waits: generated once per POST, it must survive the
# post/redirect/get to /profile, so it is parked in a short-lived cookie — the MFA step-up and OAuth
# PKCE idiom — rather than re-rendered at the POST URL.
_ENROLLMENT_COOKIE = "twofa_enrollment"
_ENROLLMENT_MAX_SECONDS = 300

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
    """The enrollment handed back by the form, or ``None`` when it is not one.

    ``ValueError`` and nothing wider: bad base64 (``binascii.Error``), undecodable bytes
    (``UnicodeDecodeError``) and malformed JSON (``JSONDecodeError``) are all subclasses of it, so
    the narrow clause covers every way a tampered or stale cookie can fail — while an
    ``AttributeError`` from a bug of ours goes on raising instead of reading as "malformed".
    """
    try:
        return json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
    except ValueError:
        return None


async def _get_profile_repo(session: RlsSession) -> ProfileRepository:
    return ProfileRepository(session)


ProfileRepo = Annotated[ProfileRepository, Depends(_get_profile_repo)]


_ACTIVITY_PAGE = 25  # facts per activity view; "Load older" grows the window by this step
_ACTIVITY_MAX = 250  # a personal feed is bounded — cap the growable window


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

    Reads on the request's own RLS session: the ``business_events`` policy scopes the journal to the
    reader (own actions + their orgs), so ``user_id`` narrows to the user's own journal. Each entry
    deep-links to the concerned entity, resolving the record's org to a handle from the user's own
    orgs (``handles``). ``who`` is dropped — every fact is the viewer's."""
    records = await EventRepository(session).search(
        user_id=user_id,
        app=app or None,
        text=q or None,
        from_dt=_parse_dt(from_dt),
        to_dt=_parse_dt(to_dt),
        limit=limit,
    )

    def link(r: BusinessEventRecord) -> str | None:
        return entity_url(r.app_name, r.entity_id, handles.get(r.org_id) if r.org_id else None)

    entries = activity_entries(records, show_actor=False, link=link)
    return {
        "activity_groups": group_activity_by_day(entries, now=clock.now()),
        "activity_has_more": len(records) >= limit and limit < _ACTIVITY_MAX,
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
    """The page context, assembled outside DI: profile routes carry no org, so the server view is
    the effective one.

    The verified-factor lookup and the passkey list are two independent GoTrue round-trips that gate
    display state only, touching neither the DB session nor each other. They are fired up front so
    they overlap each other *and* the sequential DB work below, rather than serializing three waits
    on the critical path of the site's busiest HTML page.
    """
    profile_settings = get_settings("profile").view()
    users_settings = get_settings("users").view()
    access_token = request.cookies.get("access_token", "")

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
            current_user.id, current_user.email, handle_enabled=profile_settings.handle_enabled
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

    twofa_active = False
    if twofa_task is not None:
        try:
            twofa_active = bool(await twofa_task)
        except Exception as exc:
            # Unknown is not "off": the section would claim 2FA is disabled. Say nothing instead.
            log_dependency_failure(log, "profile.twofa_lookup_failed", exc)
            two_factor_enabled = False
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
) -> Response:
    if wants_json(request):
        return JSONResponse({"detail": message}, status_code=status_code)
    ctx = await _profile_context(request, session, current_user, repo)
    ctx[key] = message
    return templates.TemplateResponse(request, "profile.html", ctx, status_code=status_code)


@router.get("/profile", responses=json_and_html(ProfileRead | ProfileStub))
async def profile_page(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
    if wants_json(request):
        profile = await repo.get_with_auto_handle(
            current_user.id, current_user.email, handle_enabled=profile_settings.handle_enabled
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


@router.get("/profile/activity", responses=json_and_html(ActivityFeedRead))
async def profile_activity(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    q: str = "",
    app: str = "",
    from_dt: str = "",
    to_dt: str = "",
    limit: int = _ACTIVITY_PAGE,
) -> Response:
    """The day-grouped activity feed as an HTMX fragment — search, type filter, date range and
    Load-older all re-render it. API callers get the same feed as JSON."""
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


@router.post("/profile/password", responses=json_and_html(Message))
async def password_change(
    request: Request,
    body: PasswordChange,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
) -> Response:
    current_password, new_password = body.current_password, body.new_password
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

    await events.emit(PasswordChanged(user_id=current_user.id), session)
    if wants_json(request):
        return JSONResponse({"message": "Password changed."})
    return _profile_redirect("password_changed")


@router.post("/profile/email", responses=json_and_html(Message))
async def email_change(
    request: Request,
    body: EmailChange,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
    if not profile_settings.email_change_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    new_email = body.new_email.strip().lower()
    current_password = body.current_password
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

    await events.emit(EmailChangeRequested(user_id=current_user.id, new_email=new_email), session)
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


@router.post("/profile/passkeys/options", response_model=dict[str, Any])
async def passkey_options(
    current_user: CurrentUser,
    users_settings: UsersSettings,
) -> JSONResponse:
    access_token = _ensure_passkeys(users_settings, current_user)
    try:
        return JSONResponse(await passkey_registration_options(access_token))
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)


@router.post("/profile/passkeys/verify", response_model=PasskeyRegistered)
async def passkey_verify(
    request: Request,
    body: PasskeyRegistration,
    current_user: CurrentUser,
    users_settings: UsersSettings,
    session: RlsSession,
) -> JSONResponse:
    access_token = _ensure_passkeys(users_settings, current_user)
    challenge_id, credential = body.challenge_id, body.credential
    if not challenge_id or not credential:
        return JSONResponse(
            {"detail": "challenge_id and credential are required."}, status_code=400
        )
    try:
        created = await verify_passkey_registration(access_token, challenge_id, credential)
    except PasskeyError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    await events.emit(PasskeyAdded(user_id=current_user.id), session)
    return JSONResponse({"message": "Passkey added.", "passkey": created})


@router.post("/profile/passkeys/{passkey_id}/delete", responses=json_and_html(Message))
async def passkey_delete(
    request: Request,
    passkey_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> Response:
    access_token = _ensure_passkeys(users_settings, current_user)
    try:
        await delete_passkey(access_token, str(passkey_id))
    except PasskeyError as e:
        return await _profile_error(
            request, session, current_user, repo, key="passkey_error", message=str(e)
        )
    await events.emit(PasskeyRemoved(user_id=current_user.id, entity_id=passkey_id), session)
    if wants_json(request):
        return JSONResponse({"message": "Passkey removed."})
    return RedirectResponse("/profile", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/profile/2fa/enroll", response_model=TotpEnrolmentRead)
async def twofa_enroll(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> Response:
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


@router.post("/profile/2fa/verify", responses=json_and_html(Message))
async def twofa_verify(
    request: Request,
    body: TotpEnrolmentCheck,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    users_settings: UsersSettings,
) -> Response:
    access_token = _ensure_two_factor(users_settings, current_user)
    factor_id, code = body.factor_id, body.code.strip()
    try:
        challenge_id = await totp_challenge(access_token, factor_id)
        tokens = await verify_totp(access_token, factor_id, challenge_id, code)
    except TotpError:
        error = "That code did not work. Try the next one from your app."
        return await _profile_error(
            request, session, current_user, repo, key="twofa_error", message=error
        )
    await events.emit(TwoFactorEnabled(user_id=current_user.id), session)
    response: Response = (
        JSONResponse({"message": "Two-factor enabled."})
        if wants_json(request)
        else _profile_redirect("twofa_enabled")
    )
    # Enrolled, the account's aal1 token is refused: keep the aal2 one the code just earned.
    set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return response


@router.delete("/profile", response_model=Message)
@router.post("/profile/delete", response_model=Message)
async def account_delete(
    request: Request,
    body: AccountDeletion,
    current_user: CurrentUser,
    admin_session: AdminSession,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
    if not profile_settings.account_deletion_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    current_password = body.current_password
    error: str | None = None
    if not current_password:
        error = "Your password is required."
    else:
        try:
            await verify_password(current_user.email, current_password)
        except WrongPassword:
            error = "Current password is incorrect."

    if error is None:
        # Serializes against a concurrent console revoke (or another self-deletion) racing the
        # same invariant through a different gate (issue #36) — held on admin_session, released
        # at its commit below.
        await lock_last_admin_guard(admin_session)
        # The JWT's ``is_admin`` claim can be stale (a promotion lands in it only on the next
        # sign-in), so the target's actual status is read fresh, the same way the console's own
        # revoke path does.
        admins = await list_server_admins()
        target_is_admin = any(u.user_id == current_user.id and u.can_act for u in admins)
        try:
            ensure_not_last_admin(
                removes_admin=True,
                target_is_admin=target_is_admin,
                admin_count=sum(1 for u in admins if u.can_act),
            )
        except LastAdminViolation:
            error = "You are the server's last admin — promote another admin first."

    if error is not None:
        return await _profile_error(
            request, session, current_user, repo, key="deletion_error", message=error
        )

    await events.emit(AccountDeleted(user_id=current_user.id, entity_id=current_user.id), session)
    # The UserDeleted fact rides the admin session — it commits iff the deletion does. Its forget
    # consumers (organizations, profile) then run asynchronously off the listener, by user id.
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


@router.post("/profile/avatar", responses=json_and_html(Message))
async def avatar_upload(
    request: Request,
    file: UploadFile,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
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
    await repo.set_avatar_path(profile, path)
    await events.emit(AvatarUpdated(user_id=current_user.id), session)
    if wants_json(request):
        return JSONResponse({"message": "Avatar updated."})
    return _profile_redirect("avatar_updated")


@router.get(
    "/profile/avatar/{user_id}",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
)
async def avatar_image(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
    profile_settings: ProfileSettings,
) -> Response:
    """Streams the avatar to whoever may read the profile — its owner and their co-members, a
    policy's decision: a profile RLS hides is a 404, not a 403 that would confirm the account."""
    if not profile_settings.avatar_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    profile = await ProfileRepository(session).get_by_user_id(user_id)
    if profile is None or not profile.avatar_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    content = await admin_storage().from_(bucket()).download(profile.avatar_path)
    media_type = _AVATAR_MEDIA.get(profile.avatar_path.rsplit(".", 1)[-1], "image/png")
    return Response(
        content, media_type=media_type, headers={"Cache-Control": "private, max-age=300"}
    )


@router.post("/profile", responses=json_and_html(ProfileRead))
async def profile_update(
    request: Request,
    body: HandleUpdate,
    current_user: CurrentUser,
    session: RlsSession,
    repo: ProfileRepo,
    profile_settings: ProfileSettings,
) -> Response:
    if not profile_settings.handle_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    profile = await repo.get_or_create(current_user.id, current_user.email)
    handle = body.handle.strip().lower()

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
        await events.emit(HandleChanged(user_id=current_user.id, new_handle=handle), session)
    if wants_json(request):
        return JSONResponse(ProfileRead.model_validate(profile).model_dump(mode="json"))
    ctx = await _profile_context(request, session, current_user, repo)
    ctx["success"] = "Profile updated."
    return templates.TemplateResponse(request, "profile.html", ctx)
