import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.domain.service import AuthenticatedUser
from app.auth.infra.security import get_current_user
from app.auth.infra.session import get_rls_session
from app.organizations.domain.models import MemberRead, OrgRole, OrganizationWithRoleRead
from app.organizations.domain.service import ensure_not_last_owner
from app.organizations.infra.repository import OrganizationRepository
from app.shared.database import get_service_session

router = APIRouter(prefix="/organizations", tags=["organizations"])


async def _resolve_emails(
    service_session: AsyncSession, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str]:
    if not user_ids:
        return {}
    result = await service_session.execute(
        text("SELECT id, email FROM auth.users WHERE id = ANY(:ids)"),
        {"ids": [str(uid) for uid in user_ids]},
    )
    return {uuid.UUID(str(row.id)): row.email for row in result}


@router.get("", response_model=list[OrganizationWithRoleRead])
async def list_organizations(
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
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
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> JSONResponse:
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if membership.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    org = await repo.get_by_id(org_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    await repo.rename(org, body.name)
    return JSONResponse(
        OrganizationWithRoleRead.model_validate({**org.__dict__, "role": "member"}).model_dump(
            mode="json"
        )
    )


@router.get("/{org_id}/members", response_model=list[MemberRead])
async def list_members(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    service_session: AsyncSession = Depends(get_service_session),
) -> list[MemberRead]:
    repo = OrganizationRepository(session)
    membership = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    members = await repo.list_members(org_id)
    emails = await _resolve_emails(service_session, [m.auth_user_id for m in members])
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
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
    service_session: AsyncSession = Depends(get_service_session),
) -> MemberRead:
    repo = OrganizationRepository(session)
    caller = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if caller is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if caller.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if body.role != OrgRole.owner:
        await ensure_not_last_owner(repo, org_id, user_id)
    membership = await repo.update_member_role(org_id, user_id, body.role)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    emails = await _resolve_emails(service_session, [membership.auth_user_id])
    return MemberRead(
        auth_user_id=membership.auth_user_id,
        email=emails.get(membership.auth_user_id, ""),
        role=membership.role,
        created_at=membership.created_at,
    )


@router.delete("/{org_id}/members/me", status_code=status.HTTP_204_NO_CONTENT)
async def leave_organization(
    org_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> None:
    user_id = uuid.UUID(current_user.id)
    repo = OrganizationRepository(session)
    await ensure_not_last_owner(repo, org_id, user_id)
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.delete("/{org_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    current_user: AuthenticatedUser = Depends(get_current_user),
    session: AsyncSession = Depends(get_rls_session),
) -> None:
    repo = OrganizationRepository(session)
    caller = await repo.get_membership(org_id, uuid.UUID(current_user.id))
    if caller is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    if caller.role != OrgRole.owner:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    await ensure_not_last_owner(repo, org_id, user_id)
    removed = await repo.remove_member(org_id, user_id)
    if not removed:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
