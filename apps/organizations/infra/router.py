import uuid
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode
from zoneinfo import available_timezones

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from apps.auth.contract.admin import find_user_id_by_email, resolve_user_emails
from apps.auth.contract.current import CurrentUser, RlsSession
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOwnerMembership,
    OrganizationsSettings,
)
from apps.organizations.contract.entity_links import entity_url
from apps.organizations.contract.events import (
    InvitationRevoked,
    InvitationSent,
    LastOwnerViolationBlocked,
    MemberLeft,
    MemberRemoved,
    MemberRoleChanged,
    OrganizationCreated,
    OrganizationRenamed,
    OrgHandleChanged,
)
from apps.organizations.contract.overviews import OverviewQuery
from apps.organizations.contract.settings_sections import OrgSettingsSectionQuery
from apps.organizations.domain.exceptions import (
    LastOwnerViolation,
    OrgLimitReached,
    PendingInvitationExists,
)
from apps.organizations.domain.models import (
    InvitationRead,
    MemberRead,
    OrganizationWithRoleRead,
    OrgRole,
)
from apps.organizations.domain.service import ensure_no_pending_invitation, ensure_not_last_owner
from apps.organizations.infra.emails import invitation_email
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared import clock
from apps.shared.contribs import contribs
from apps.shared.email import enqueue_email
from apps.shared.events.bus import events
from apps.shared.events.models import BusinessEventLog
from apps.shared.events.repository import EventRepository
from apps.shared.events.timeline import (
    activity_entries,
    activity_stats,
    group_activity_by_day,
    heatmap_calendar,
)
from apps.shared.http import delete_response, mutation_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.page import fullpage_context
from apps.shared.slug_registry import validate_handle

# A curated shortlist for the org timezone picker — any IANA zone is accepted by the
# endpoint (validated against zoneinfo), but the dropdown stays scannable.
COMMON_TIMEZONES: tuple[str, ...] = (
    "UTC",
    "Europe/London",
    "Europe/Paris",
    "Europe/Berlin",
    "Europe/Madrid",
    "Europe/Moscow",
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "America/Sao_Paulo",
    "Africa/Cairo",
    "Asia/Dubai",
    "Asia/Kolkata",
    "Asia/Shanghai",
    "Asia/Tokyo",
    "Australia/Sydney",
    "Pacific/Auckland",
)

# Collection router — multi-org, not scoped by a handle. Mounted at the root.
router = APIRouter(prefix="/organizations", tags=["organizations"])

# Org-scoped router — every route resolves the org from the {org_handle} path
# parameter (via CurrentOrg) and negotiates JSON vs HTML. Mounted under /{org_handle}.
org_router = APIRouter(tags=["organizations"])


async def _get_org_repo(session: RlsSession) -> OrganizationRepository:
    return OrganizationRepository(session)


OrgRepo = Annotated[OrganizationRepository, Depends(_get_org_repo)]


def _org_with_role_json(org, role) -> JSONResponse:
    return JSONResponse(
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": role}).model_dump(
            mode="json"
        )
    )


async def _pending_invitations_html(request, repo, org_id, caller_role: str) -> str:
    org = await repo.get(org_id)
    org_handle = request.path_params.get("org_handle", org.handle if org else "")
    invitations = [InvitationRead.model_validate(i) for i in await repo.list_invitations(org_id)]
    return bytes(
        templates.TemplateResponse(
            request,
            "organizations/_pending_invitations.html",
            {
                "caller_role": caller_role,
                "invitations": invitations,
                "org_handle": org_handle,
            },
        ).body
    ).decode()


async def _emit_last_owner_violation(
    current_user: CurrentUser,
    org_id: uuid.UUID,
    target_user_id: uuid.UUID | None = None,
) -> None:
    # ip rides in from the request contextvars; the persister enriches it at write time.
    await events.emit(
        LastOwnerViolationBlocked(user_id=current_user.id, org_id=org_id, entity_id=target_user_id)
    )


async def _build_members(repo: OrganizationRepository, org_id: uuid.UUID) -> list[MemberRead]:
    raw_members = await repo.list_members(org_id)
    emails = await resolve_user_emails([m.auth_user_id for m in raw_members])
    return [
        MemberRead(
            auth_user_id=m.auth_user_id,
            email=emails.get(m.auth_user_id, ""),
            role=m.role,
            created_at=m.created_at,
        )
        for m in raw_members
    ]


# ── Collection (multi-org) ─────────────────────────────────────────────────────


@router.post("", response_model=None)
async def create_organization(
    request: Request,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_settings: OrganizationsSettings,
) -> Response:
    body = await parse_body(request)
    name = str(body.get("name", "")).strip()
    user_id = current_user.id

    max_orgs = org_settings.max_owned_orgs_per_user
    if max_orgs >= 0 and await repo.count_owned_by(user_id) >= max_orgs:
        msg = OrgLimitReached.message(max_orgs)
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        return HTMLResponse(
            f'<div role="alert" class="alert-error">{msg}</div>',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    org = await repo.create_with_owner(name, user_id)
    # Commit before emitting: OrganizationCreated triggers the welcome seeders, each reading the
    # org back on its own admin session — they must see a committed row (session has
    # expire_on_commit=False, so `org` stays usable for the response below).
    await repo.session.commit()
    await events.emit(
        OrganizationCreated(
            user_id=current_user.id, org_id=org.id, entity_id=org.id, entity_name=name
        )
    )
    result = OrganizationWithRoleRead.model_validate({**org.__dict__, "role": OrgRole.owner})
    return mutation_response(
        request,
        obj=result,
        redirect_url=f"/{org.handle}/dashboard",
        htmx_redirect_url=f"/{org.handle}/dashboard",
        status_code=status.HTTP_201_CREATED,
    )


@router.get("", response_model=list[OrganizationWithRoleRead])
async def list_organizations(
    current_user: CurrentUser,
    repo: OrgRepo,
) -> list[OrganizationWithRoleRead]:
    pairs = await repo.list_with_role_for_user(current_user.id)
    return [
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": role})
        for org, role in pairs
    ]


# ── Org-scoped pages ────────────────────────────────────────────────────────────


_ACTIVITY_PAGE = 8  # rows shown by default; "Load older" grows the window by this step
_ACTIVITY_MAX = 250  # the dashboard trail is bounded — cap the growable window


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
    org_id: uuid.UUID,
    org_handle: str,
    *,
    q: str = "",
    app: str = "",
    from_dt: str = "",
    to_dt: str = "",
    limit: int = _ACTIVITY_PAGE,
) -> dict:
    """The org's day-grouped activity feed under the given filters — shared by the dashboard's
    initial render and the ``/{org}/dashboard/activity`` HTMX fragment.

    Reads on the request's own RLS session: the ``business_events`` policy lets a member read
    every event of any org they belong to, so ``org_id`` narrows to this org's trail. Each entry
    keeps its actor (``who did what``, a shared org feed) and deep-links to the concerned entity
    where the app exposes a page. Exposes only humanized labels and moments — never payloads."""
    rows = await EventRepository(session).search(
        org_id=org_id,
        app=app or None,
        text=q or None,
        from_dt=_parse_dt(from_dt),
        to_dt=_parse_dt(to_dt),
        limit=limit,
    )

    def link(r: BusinessEventLog) -> str | None:
        return entity_url(r.kind, r.entity_id, org_handle)

    entries = activity_entries(rows, link=link)
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


@org_router.get("/dashboard", response_class=HTMLResponse)
async def org_dashboard(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> HTMLResponse:
    org = or_404(await repo.get(org_id))
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await fullpage_context(session, current_user, org=org, org_handle=org_handle)
    ctx["overviews"] = sorted(
        await contribs.collect(OverviewQuery(session, org_id)), key=lambda o: o.key
    )
    # The org's own numbers — apps contribute cards below, these two are organizations'.
    ctx["member_count"] = len(await repo.list_members(org_id))
    ctx["pending_invitations"] = len(await repo.list_invitations(org_id))
    counts = await EventRepository(session).daily_counts(org_id=org_id)
    now = clock.now()
    ctx["activity_calendar"] = heatmap_calendar(counts, now=now, since=org.created_at)
    ctx["activity_stats"] = activity_stats(counts, now=now)
    ctx.update(await _activity_context(session, org_id, org_handle))
    return templates.TemplateResponse(request, "organizations/dashboard.html", ctx)


@org_router.get("/dashboard/activity", response_model=None)
async def org_dashboard_activity(
    request: Request,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentMembership,
    q: str = "",
    app: str = "",
    from_dt: str = "",
    to_dt: str = "",
    limit: int = _ACTIVITY_PAGE,
) -> HTMLResponse | JSONResponse:
    """The org's day-grouped activity feed as an HTMX fragment — search, type filter, date range
    and Load-older all re-render it. API callers get the same trail as JSON."""
    limit = max(_ACTIVITY_PAGE, min(limit, _ACTIVITY_MAX))
    org = or_404(await repo.get(org_id))
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await _activity_context(
        session, org_id, org_handle, q=q, app=app, from_dt=from_dt, to_dt=to_dt, limit=limit
    )
    if wants_json(request):
        entries = [e for g in ctx["activity_groups"] for e in g["entries"]]
        return JSONResponse({"entries": [{**e, "ts": e["ts"].isoformat()} for e in entries]})
    ctx["org_handle"] = org_handle
    return templates.TemplateResponse(request, "organizations/activity_feed.html", ctx)


@org_router.get("/dashboard/overviews.json")
async def org_dashboard_overviews(
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> JSONResponse:
    overviews = sorted(await contribs.collect(OverviewQuery(session, org_id)), key=lambda o: o.key)
    return JSONResponse([{"key": o.key, "title": o.title, "data": o.data} for o in overviews])


async def _settings_context(
    session, current_user, org, org_handle, role: str, *, repo: OrganizationRepository
) -> dict:
    """Full template context for the settings page: fullpage chrome, the members panel
    (Members tab) and the settings sections apps contribute (:class:`OrgSettingsSectionQuery`,
    API keys tab). Shared by every route that renders ``settings.html`` so all tab loops
    are always defined."""
    ctx = await fullpage_context(session, current_user, org=org, org_handle=org_handle, role=role)
    ctx["settings_sections"] = sorted(
        await contribs.collect(OrgSettingsSectionQuery(session, org.id, role == "owner")),
        key=lambda s: s.order,
    )
    ctx["members"] = await _build_members(repo, org.id)
    ctx["caller_role"] = role
    ctx["current_user"] = current_user
    invitations: list[InvitationRead] = []
    if role == "owner":
        raw_invs = await repo.list_invitations(org.id)
        invitations = [InvitationRead.model_validate(inv) for inv in raw_invs]
    ctx["invitations"] = invitations
    # The org's current zone always appears in the picker even if it is not in the shortlist.
    ctx["timezones"] = sorted({*COMMON_TIMEZONES, org.timezone})
    ctx["current_timezone"] = org.timezone
    return ctx


@org_router.get("/settings", response_class=HTMLResponse)
async def org_settings(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
):
    org = or_404(await repo.get(org_id))
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await _settings_context(
        session, current_user, org, org_handle, membership.role.value, repo=repo
    )
    ctx["saved"] = "saved" in request.query_params
    return templates.TemplateResponse(request, "organizations/settings.html", ctx)


@org_router.get("/members", response_class=HTMLResponse)
async def list_members(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentMembership,
):
    org = or_404(await repo.get(org_id))
    members = await _build_members(repo, org_id)
    if wants_json(request):
        return JSONResponse([m.model_dump(mode="json") for m in members])
    invitations: list[InvitationRead] = []
    if membership.role == OrgRole.owner:
        raw_invs = await repo.list_invitations(org_id)
        invitations = [InvitationRead.model_validate(inv) for inv in raw_invs]
    org_handle = request.path_params.get("org_handle", org.handle)
    ctx = await fullpage_context(
        session,
        current_user,
        current_user=current_user,
        org=org,
        org_handle=org_handle,
        caller_role=membership.role.value,
        members=members,
        invitations=invitations,
    )
    return templates.TemplateResponse(request, "organizations/members.html", ctx)


# ── Settings mutations ──────────────────────────────────────────────────────────


@org_router.patch("", response_class=HTMLResponse)
async def rename_organization(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
):
    body = await parse_body(request)
    name = str(body.get("name", "")).strip()
    org = or_404(await repo.get(org_id))
    error = None
    if not name:
        error = "Name cannot be empty."
    elif len(name) > 255:
        error = "Name must be 255 characters or fewer."
    if error is not None:
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)
        org_handle = request.path_params.get("org_handle", org.handle)
        ctx = await _settings_context(
            session, current_user, org, org_handle, membership.role.value, repo=repo
        )
        ctx["name_error"] = error
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=422
        )
    await repo.rename(org, name)
    await events.emit(
        OrganizationRenamed(
            user_id=current_user.id, org_id=org_id, entity_id=org_id, entity_name=name
        )
    )
    if wants_json(request):
        return _org_with_role_json(org, membership.role)
    return RedirectResponse(url=f"/{org.handle}/settings?saved=1", status_code=303)


@org_router.patch("/handle", response_class=HTMLResponse)
async def update_org_handle(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
):
    body = await parse_body(request)
    handle = str(body.get("handle", "")).strip().lower()
    org = or_404(await repo.get(org_id))
    validation_error = validate_handle(handle)
    error = validation_error[1] if validation_error else None
    code = validation_error[0] if validation_error else status.HTTP_422_UNPROCESSABLE_ENTITY
    if error is None and not await repo.is_handle_available(handle, org_id):
        error = f"'{handle}' is already taken."
        code = status.HTTP_409_CONFLICT
    if error is not None:
        if wants_json(request):
            raise HTTPException(status_code=code, detail=error)
        org_handle = request.path_params.get("org_handle", org.handle)
        ctx = await _settings_context(
            session, current_user, org, org_handle, membership.role.value, repo=repo
        )
        ctx["handle_error"] = error
        ctx["handle_value"] = handle
        response = templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=code
        )
        response.headers["HX-Push-Url"] = "false"
        return response
    await repo.update_handle(org, handle)
    await events.emit(
        OrgHandleChanged(
            user_id=current_user.id, org_id=org_id, entity_id=org_id, entity_name=handle
        )
    )
    if wants_json(request):
        return _org_with_role_json(org, membership.role)
    return RedirectResponse(url=f"/{handle}/settings?saved=1", status_code=303)


@org_router.patch("/timezone", response_class=HTMLResponse)
async def update_org_timezone(
    request: Request,
    current_user: CurrentUser,
    session: RlsSession,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
):
    body = await parse_body(request)
    timezone = str(body.get("timezone", "")).strip()
    org = or_404(await repo.get(org_id))
    if timezone not in available_timezones():
        error = f"'{timezone}' is not a valid timezone."
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error)
        org_handle = request.path_params.get("org_handle", org.handle)
        ctx = await _settings_context(
            session, current_user, org, org_handle, membership.role.value, repo=repo
        )
        ctx["timezone_error"] = error
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=422
        )
    await repo.set_timezone(org, timezone)
    if wants_json(request):
        return _org_with_role_json(org, membership.role)
    return RedirectResponse(url=f"/{org.handle}/settings?saved=1", status_code=303)


# ── Members ─────────────────────────────────────────────────────────────────────


@org_router.delete("/members/me", response_class=HTMLResponse)
async def leave_organization(
    request: Request,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> Response:
    user_id = current_user.id
    or_404(await repo.get(org_id))
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        await _emit_last_owner_violation(current_user, org_id)
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        msg = "You are the last owner. Transfer ownership before leaving."
        return HTMLResponse(
            f'<div role="alert" class="alert-error">{msg}</div>',
            status_code=status.HTTP_403_FORBIDDEN,
        )
    await repo.remove_member(org_id, user_id)
    await events.emit(MemberLeft(user_id=current_user.id, org_id=org_id))
    return delete_response(request, htmx_redirect_url="/profile")


@org_router.patch("/members/{user_id}", response_class=HTMLResponse)
async def update_member_role(
    request: Request,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    body = await parse_body(request)
    role = str(body.get("role", ""))
    org = or_404(await repo.get(org_id))
    try:
        new_role = OrgRole(role)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY) from exc
    if new_role != OrgRole.owner:
        try:
            await ensure_not_last_owner(repo, org_id, user_id)
        except LastOwnerViolation as exc:
            await _emit_last_owner_violation(current_user, org_id, target_user_id=user_id)
            if wants_json(request):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            return HTMLResponse(
                "You cannot demote the last owner.", status_code=status.HTTP_403_FORBIDDEN
            )
    updated = await repo.update_member_role(org_id, user_id, new_role)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await events.emit(
        MemberRoleChanged(
            user_id=current_user.id,
            org_id=org_id,
            entity_id=user_id,
            role=new_role.value,
        )
    )
    emails = await resolve_user_emails([updated.auth_user_id])
    member = MemberRead(
        auth_user_id=updated.auth_user_id,
        email=emails.get(updated.auth_user_id, ""),
        role=updated.role,
        created_at=updated.created_at,
    )
    if wants_json(request):
        return JSONResponse(member.model_dump(mode="json"))
    org_handle = request.path_params.get("org_handle", org.handle)
    return templates.TemplateResponse(
        request,
        "organizations/_member_row.html",
        {
            "m": member,
            "caller_role": membership.role.value,
            "current_user": current_user,
            "org": org,
            "org_handle": org_handle,
        },
    )


@org_router.delete("/members/{user_id}", response_class=HTMLResponse)
async def remove_member(
    request: Request,
    user_id: uuid.UUID,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        await _emit_last_owner_violation(current_user, org_id, target_user_id=user_id)
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return HTMLResponse(
            "You cannot remove the last owner.", status_code=status.HTTP_403_FORBIDDEN
        )
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await events.emit(MemberRemoved(user_id=current_user.id, org_id=org_id, entity_id=user_id))
    # HTML stays on the members page and re-renders an OOB count, not a redirect,
    # so this only ever uses delete_response's JSON branch.
    if wants_json(request):
        return delete_response(request)
    members = await _build_members(repo, org_id)
    count = len(members)
    label = f"{count} member{'s' if count != 1 else ''}"
    cls = "text-sm text-base-content/70"
    oob = f'<p id="member-count" aria-live="polite" hx-swap-oob="true" class="{cls}">{label}</p>'
    return HTMLResponse(oob, status_code=status.HTTP_200_OK)


# ── Invitations ─────────────────────────────────────────────────────────────────


@org_router.post("/invitations", response_class=HTMLResponse)
async def create_invitation(
    request: Request,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
    org_settings: OrganizationsSettings,
) -> Response:
    body = await parse_body(request)
    # Canonicalise once: the accept RPC matches case-insensitively (lower()), so without this
    # `Foo@x.com` and `foo@x.com` slip past the pending-dedup and both stay acceptable.
    email = str(body.get("email", "")).strip().lower()
    error: str | None = None
    invitation = None

    existing_user_id = await find_user_id_by_email(email)
    if existing_user_id is not None and await repo.get_membership(org_id, existing_user_id):
        error = "already a member"

    max_invites = org_settings.max_invitations_per_org
    if error is None and max_invites >= 0:
        pending = len(await repo.list_invitations(org_id))
        if pending >= max_invites:
            error = f"invitation limit reached ({max_invites} pending)"

    if error is None:
        try:
            await ensure_no_pending_invitation(repo, org_id, email)
        except PendingInvitationExists as exc:
            error = str(exc)
        else:
            invitation = await repo.create_invitation(
                org_id=org_id,
                email=email,
                role=OrgRole.member,
                invited_by=current_user.id,
            )
            await events.emit(
                InvitationSent(user_id=current_user.id, org_id=org_id, entity_name=email)
            )

    link = ""
    if invitation is not None:
        base_url = str(request.base_url).rstrip("/")
        link = f"{base_url}/invitations/{invitation.token}"
        inviting_org = await repo.get(org_id)
        org_name = inviting_org.name if inviting_org else ""
        # Outbox: the mail task commits (or rolls back) with the invitation itself.
        await enqueue_email(repo.session, invitation_email(to=email, org_name=org_name, link=link))

    if wants_json(request):
        if error is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error)
        assert invitation is not None
        return JSONResponse(
            InvitationRead.model_validate(invitation).model_dump(mode="json"),
            status_code=status.HTTP_201_CREATED,
        )

    if invitation is None or error is not None:
        return templates.TemplateResponse(
            request,
            "organizations/_invite_result.html",
            {"email": email, "link": link, "error": error},
        )

    # Success: return invite result + OOB swap to refresh the pending invitations list.
    result_html = bytes(
        templates.TemplateResponse(
            request,
            "organizations/_invite_result.html",
            {"email": email, "link": link, "error": None},
        ).body
    ).decode()
    oob_html = await _pending_invitations_html(request, repo, org_id, membership.role.value)
    return HTMLResponse(result_html + oob_html)


@org_router.get("/invitations", response_model=list[InvitationRead])
async def list_invitations(
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> list[InvitationRead]:
    invitations = await repo.list_invitations(org_id)
    return [InvitationRead.model_validate(inv) for inv in invitations]


@org_router.delete("/invitations/{invitation_id}", response_class=HTMLResponse)
async def revoke_invitation(
    request: Request,
    invitation_id: uuid.UUID,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    invitation = or_404(await repo.get_invitation_by_id(org_id, invitation_id))
    await repo.revoke_invitation(invitation)
    await events.emit(
        InvitationRevoked(user_id=current_user.id, org_id=org_id, invitation_id=invitation_id)
    )
    # HTML re-renders the pending-invitations fragment in place, not a redirect,
    # so this only ever uses delete_response's JSON branch.
    if wants_json(request):
        return delete_response(request)
    pending_invitations_html = await _pending_invitations_html(
        request, repo, org_id, membership.role.value
    )
    return HTMLResponse(pending_invitations_html, status_code=status.HTTP_200_OK)
