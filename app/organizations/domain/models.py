import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.persistence.base import Base


class OrgRole(StrEnum):
    owner = "owner"
    member = "member"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    handle: Mapped[str] = mapped_column(default="")
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    __mapper_args__ = {"version_id_col": version}


class Membership(Base):
    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", create_type=False), nullable=False, default=OrgRole.member
    )
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    __mapper_args__ = {"version_id_col": version}


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
    invited_by: Mapped[uuid.UUID | None]
    status: Mapped[InvitationStatus] = mapped_column(
        SAEnum(InvitationStatus, name="invitation_status", create_type=False),
        nullable=False,
        default=InvitationStatus.pending,
    )
    version: Mapped[int] = mapped_column(default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)

    __mapper_args__ = {"version_id_col": version}


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
    handle: str
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
