import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.infra.user_repository import find_user_id_by_email, resolve_user_emails
from app.organizations.domain.exceptions import LastOwnerViolation, PendingInvitationExists
from app.organizations.domain.models import (
    InvitationRead,
    MemberRead,
    OrganizationWithRoleRead,
    OrgRole,
)
from app.organizations.domain.service import ensure_no_pending_invitation, ensure_not_last_owner
from app.organizations.infra.repository import OrganizationRepository
from app.shared.dependencies import CurrentUser, OwnerMembership, RlsSession
from app.shared.observability.audit import record_audit_event

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.get("", response_model=list[OrganizationWithRoleRead])
async def list_organizations(
    current_user: CurrentUser,
    session: RlsSession,
) -> list[OrganizationWithRoleRead]:
    repo = OrganizationRepository(session)
    pairs = await repo.list_with_role_for_user(uuid.UUID(current_user.id))
    return [
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": role})
        for org, role in pairs
    ]


class RenameOrgBody(BaseModel):
    name: str


@router.patch("/{org_id}")
async def rename_organization(
    org_id: uuid.UUID,
    body: RenameOrgBody,
    owner: OwnerMembership,
    session: RlsSession,
) -> JSONResponse:
    repo = OrganizationRepository(session)
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await repo.rename(org, body.name)
    return JSONResponse(
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": owner.role}).model_dump(
            mode="json"
        )
    )


@router.get("/{org_id}/members", response_model=list[MemberRead])
async def list_members(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
) -> list[MemberRead]:
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    members = await repo.list_members(org_id)
    emails = await resolve_user_emails([m.auth_user_id for m in members])
    return [
        MemberRead(
            auth_user_id=m.auth_user_id,
            email=emails.get(m.auth_user_id, ""),
            role=m.role,
            created_at=m.created_at,
        )
        for m in members
    ]


class UpdateRoleBody(BaseModel):
    role: OrgRole


@router.patch("/{org_id}/members/{user_id}", response_model=MemberRead)
async def update_member_role(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    body: UpdateRoleBody,
    _: OwnerMembership,
    session: RlsSession,
) -> MemberRead:
    repo = OrganizationRepository(session)
    if body.role != OrgRole.owner:
        try:
            await ensure_not_last_owner(repo, org_id, user_id)
        except LastOwnerViolation as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    membership = await repo.update_member_role(org_id, user_id, body.role)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    emails = await resolve_user_emails([membership.auth_user_id])
    return MemberRead(
        auth_user_id=membership.auth_user_id,
        email=emails.get(membership.auth_user_id, ""),
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete("/{org_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_organization(
    org_id: uuid.UUID,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    session: RlsSession,
) -> None:
    user_id = uuid.UUID(current_user.id)
    repo = OrganizationRepository(session)
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    record_audit_event(
        bg, level="info", event="org.member_left", user_id=current_user.id, org_id=str(org_id)
    )


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    _: OwnerMembership,
    session: RlsSession,
) -> None:
    repo = OrganizationRepository(session)
    try:
        await ensure_not_last_owner(repo, org_id, user_id)
    except LastOwnerViolation as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    record_audit_event(
        bg,
        level="info",
        event="org.member_removed",
        user_id=current_user.id,
        org_id=str(org_id),
        target_user_id=str(user_id),
    )


class InvitationCreateBody(BaseModel):
    email: str


@router.post(
    "/{org_id}/invitations", response_model=InvitationRead, status_code=status.HTTP_201_CREATED
)
async def create_invitation(
    org_id: uuid.UUID,
    body: InvitationCreateBody,
    bg: BackgroundTasks,
    current_user: CurrentUser,
    _: OwnerMembership,
    session: RlsSession,
) -> InvitationRead:
    repo = OrganizationRepository(session)
    existing_user_id = await find_user_id_by_email(body.email)
    if existing_user_id is not None:
        existing_membership = await repo.get_membership(org_id, existing_user_id)
        if existing_membership is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already a member")

    try:
        await ensure_no_pending_invitation(repo, org_id, body.email)
    except PendingInvitationExists as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    invitation = await repo.create_invitation(
        org_id=org_id,
        email=body.email,
        role=OrgRole.member,
        invited_by=uuid.UUID(current_user.id),
    )
    record_audit_event(
        bg,
        level="info",
        event="org.invitation_sent",
        user_id=current_user.id,
        org_id=str(org_id),
        invitee_email=body.email,
    )
    return InvitationRead.model_validate(invitation)


@router.get("/{org_id}/invitations", response_model=list[InvitationRead])
async def list_invitations(
    org_id: uuid.UUID,
    current_user: CurrentUser,
    session: RlsSession,
) -> list[InvitationRead]:
    repo = OrganizationRepository(session)
    caller = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if caller is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    invitations = await repo.list_invitations(org_id)
    return [InvitationRead.model_validate(inv) for inv in invitations]


@router.delete("/{org_id}/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    org_id: uuid.UUID,
    invitation_id: uuid.UUID,
    _: OwnerMembership,
    session: RlsSession,
) -> None:
    repo = OrganizationRepository(session)
    invitation = await repo.get_invitation_by_id(org_id, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await repo.revoke_invitation(invitation)
