import uuid
from datetime import datetime
from enum import StrEnum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.persistence.base import Base
from app.shared.clock import now


class OrgRole(StrEnum):
    owner = "owner"
    member = "member"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )


class Membership(Base):
    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", create_type=False), nullable=False, default=OrgRole.member
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )


class InvitationStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class OrgInvitation(Base):
    __tablename__ = "org_invitations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", create_type=False), nullable=False, default=OrgRole.member
    )
    token: Mapped[uuid.UUID] = mapped_column(default=uuid.uuid4, unique=True)
    invited_by: Mapped[uuid.UUID]
    status: Mapped[InvitationStatus] = mapped_column(
        SAEnum(InvitationStatus, name="invitation_status", create_type=False),
        nullable=False,
        default=InvitationStatus.pending,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=now
    )


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: OrgRole
    token: uuid.UUID
    status: InvitationStatus
    created_at: datetime


class OrganizationCreate(BaseModel):
    name: str


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    created_at: datetime


class OrganizationWithRoleRead(OrganizationRead):
    role: OrgRole


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    org_id: uuid.UUID
    auth_user_id: uuid.UUID
    role: OrgRole


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    auth_user_id: uuid.UUID
    email: str
    role: OrgRole
    created_at: datetime


class OrganizationService(BaseModel):
    """Données agrégées utiles pour un membre : org + son rôle."""

    org: OrganizationRead
    role: OrgRole
    is_active: bool | None = None
