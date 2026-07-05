import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from apps.auth.contract.admin import find_user_id_by_email, resolve_user_emails
from apps.auth.contract.current import CurrentUser, RlsSession
from apps.organizations.contract import settings
from apps.organizations.contract.current import (
    CurrentMembership,
    CurrentOrg,
    CurrentOwnerMembership,
)
from apps.organizations.contract.overviews import OverviewQuery
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
from apps.organizations.infra.repository import OrganizationRepository
from apps.shared.host import host
from apps.shared.http import delete_response, mutation_response, or_404, parse_body, wants_json
from apps.shared.http.templates import templates
from apps.shared.observability.audit import audit
from apps.shared.page import fullpage_context
from apps.shared.slug_registry import validate_handle

# Collection router — multi-org, not scoped by a handle. Mounted at the root.
router = APIRouter(prefix="/organizations", tags=["organizations"])

# Org-scoped router — every route resolves the org from the {org_handle} path
# parameter (via CurrentOrg) and negotiates JSON vs HTML. Mounted under /{org_handle}.
org_router = APIRouter(tags=["organizations"])


async def _get_org_repo(session: RlsSession) -> OrganizationRepository:
    return OrganizationRepository(session)


OrgRepo = Annotated[OrganizationRepository, Depends(_get_org_repo)]


def _audit_last_owner_violation(
    bg: BackgroundTasks,
    request: Request,
    current_user: CurrentUser,
    org_id: uuid.UUID,
    **extra: str,
) -> None:
    audit(
        bg,
        "organizations.last_owner_violation",
        level="warning",
        user_id=current_user.id,
        org_id=org_id,
        ip=request.client.host if request.client else None,
        **extra,
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
    bg: BackgroundTasks,
    current_user: CurrentUser,
    repo: OrgRepo,
) -> Response:
    body = await parse_body(request)
    name = str(body.get("name", "")).strip()
    user_id = uuid.UUID(current_user.id)

    max_orgs = settings.max_owned_orgs_per_user
    if max_orgs >= 0 and await repo.count_owned_by(user_id) >= max_orgs:
        msg = OrgLimitReached.message(max_orgs)
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=msg)
        return HTMLResponse(
            f'<div role="alert" class="alert-error">{msg}</div>',
            status_code=status.HTTP_403_FORBIDDEN,
        )

    org = await repo.create_with_owner(name, user_id)
    audit(
        bg,
        "organizations.created",
        user_id=current_user.id,
        org_id=org.id,
        name=name,
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
    pairs = await repo.list_with_role_for_user(uuid.UUID(current_user.id))
    return [
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": role})
        for org, role in pairs
    ]


# ── Org-scoped pages ────────────────────────────────────────────────────────────


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
        await host.events.collect(OverviewQuery(session, org_id)), key=lambda o: o.key
    )
    return templates.TemplateResponse(request, "organizations/dashboard.html", ctx)


@org_router.get("/dashboard/overviews.json")
async def org_dashboard_overviews(
    session: RlsSession,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> JSONResponse:
    overviews = sorted(
        await host.events.collect(OverviewQuery(session, org_id)), key=lambda o: o.key
    )
    return JSONResponse([{"key": o.key, "title": o.title, "data": o.data} for o in overviews])


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
    ctx = await fullpage_context(
        session, current_user, org=org, org_handle=org_handle, role=membership.role.value
    )
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
        ctx = await fullpage_context(
            session, current_user, org=org, org_handle=org_handle, role=membership.role.value
        )
        ctx["name_error"] = error
        return templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=422
        )
    await repo.rename(org, name)
    if wants_json(request):
        return JSONResponse(
            OrganizationWithRoleRead.model_validate(
                {**org.__dict__, "role": membership.role}
            ).model_dump(mode="json")
        )
    return RedirectResponse(url=f"/{org.handle}/settings", status_code=303)


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
        ctx = await fullpage_context(
            session, current_user, org=org, org_handle=org_handle, role=membership.role.value
        )
        ctx["handle_error"] = error
        response = templates.TemplateResponse(
            request, "organizations/settings.html", ctx, status_code=code
        )
        response.headers["HX-Push-Url"] = "false"
        return response
    await repo.update_handle(org, handle)
    if wants_json(request):
        return JSONResponse(
            OrganizationWithRoleRead.model_validate(
                {**org.__dict__, "role": membership.role}
            ).model_dump(mode="json")
        )
    return RedirectResponse(url=f"/{handle}/settings", status_code=303)


# ── Members ─────────────────────────────────────────────────────────────────────


@org_router.delete("/members/me", response_class=HTMLResponse)
async def leave_organization(
    request: Request,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentMembership,
) -> Response:
    user_id = uuid.UUID(current_user.id)
    or_404(await repo.get(org_id))
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        _audit_last_owner_violation(bg, request, current_user, org_id)
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        msg = "You are the last owner. Transfer ownership before leaving."
        return HTMLResponse(
            f'<div role="alert" class="alert-error">{msg}</div>',
            status_code=status.HTTP_403_FORBIDDEN,
        )
    await repo.remove_member(org_id, user_id)
    audit(
        bg,
        "organizations.member_left",
        user_id=current_user.id,
        org_id=org_id,
    )
    return delete_response(request, htmx_redirect_url="/profile")


@org_router.patch("/members/{user_id}", response_class=HTMLResponse)
async def update_member_role(
    request: Request,
    user_id: uuid.UUID,
    bg: BackgroundTasks,
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
            _audit_last_owner_violation(
                bg, request, current_user, org_id, target_user_id=str(user_id)
            )
            if wants_json(request):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
            return HTMLResponse(
                "You cannot demote the last owner.", status_code=status.HTTP_403_FORBIDDEN
            )
    updated = await repo.update_member_role(org_id, user_id, new_role)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    audit(
        bg,
        "organizations.member_role_changed",
        user_id=current_user.id,
        org_id=org_id,
        target_user_id=str(user_id),
        role=new_role.value,
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
    bg: BackgroundTasks,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        _audit_last_owner_violation(bg, request, current_user, org_id, target_user_id=str(user_id))
        if wants_json(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
        return HTMLResponse(
            "You cannot remove the last owner.", status_code=status.HTTP_403_FORBIDDEN
        )
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    audit(
        bg,
        "organizations.member_removed",
        user_id=current_user.id,
        org_id=org_id,
        target_user_id=str(user_id),
    )
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
    bg: BackgroundTasks,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    body = await parse_body(request)
    email = str(body.get("email", ""))
    error: str | None = None
    invitation = None

    existing_user_id = await find_user_id_by_email(email)
    if existing_user_id is not None and await repo.get_membership(org_id, existing_user_id):
        error = "already a member"

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
                invited_by=uuid.UUID(current_user.id),
            )
            audit(
                bg,
                "organizations.invitation_sent",
                user_id=current_user.id,
                org_id=org_id,
                target_email=email,
            )

    if wants_json(request):
        if error is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=error)
        assert invitation is not None
        return JSONResponse(
            InvitationRead.model_validate(invitation).model_dump(mode="json"),
            status_code=status.HTTP_201_CREATED,
        )

    link = ""
    if invitation is not None:
        base_url = str(request.base_url).rstrip("/")
        link = f"{base_url}/invitations/{invitation.token}"

    if invitation is None or error is not None:
        return templates.TemplateResponse(
            request,
            "organizations/_invite_result.html",
            {"email": email, "link": link, "error": error},
        )

    # Success: return invite result + OOB swap to refresh the pending invitations list.
    org = await repo.get(org_id)
    org_handle = request.path_params.get("org_handle", org.handle if org else "")
    raw_invs = await repo.list_invitations(org_id)
    invitations = [InvitationRead.model_validate(inv) for inv in raw_invs]
    result_html = bytes(
        templates.TemplateResponse(
            request,
            "organizations/_invite_result.html",
            {"email": email, "link": link, "error": None},
        ).body
    ).decode()
    oob_html = bytes(
        templates.TemplateResponse(
            request,
            "organizations/_pending_invitations.html",
            {
                "caller_role": membership.role.value,
                "invitations": invitations,
                "org_handle": org_handle,
            },
        ).body
    ).decode()
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
    bg: BackgroundTasks,
    current_user: CurrentUser,
    repo: OrgRepo,
    org_id: CurrentOrg,
    membership: CurrentOwnerMembership,
) -> Response:
    invitation = or_404(await repo.get_invitation_by_id(org_id, invitation_id))
    await repo.revoke_invitation(invitation)
    audit(
        bg,
        "organizations.invitation_revoked",
        user_id=current_user.id,
        org_id=org_id,
        invitation_id=str(invitation_id),
    )
    # HTML re-renders the pending-invitations fragment in place, not a redirect,
    # so this only ever uses delete_response's JSON branch.
    if wants_json(request):
        return delete_response(request)
    org = await repo.get(org_id)
    org_handle = request.path_params.get("org_handle", org.handle if org else "")
    raw_invs = await repo.list_invitations(org_id)
    invitations = [InvitationRead.model_validate(inv) for inv in raw_invs]
    pending_invitations_html = bytes(
        templates.TemplateResponse(
            request,
            "organizations/_pending_invitations.html",
            {
                "caller_role": membership.role.value,
                "invitations": invitations,
                "org_handle": org_handle,
            },
        ).body
    ).decode()
    return HTMLResponse(pending_invitations_html, status_code=status.HTTP_200_OK)
