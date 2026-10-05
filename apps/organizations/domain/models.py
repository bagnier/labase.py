import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class OrgRole(StrEnum):
    owner = "owner"
    member = "member"


class Organization(Base, UUIDPk, Versioned, Timestamped):
    __tablename__ = "organizations"
    __table_args__ = (UniqueConstraint("handle"),)

    name: Mapped[str]
    handle: Mapped[str] = mapped_column(default="")
    # IANA timezone for the org's dates.
    timezone: Mapped[str] = mapped_column(default="UTC")
    # The org every account gets at sign-up; set once.
    is_personal: Mapped[bool] = mapped_column(default=False)


class Membership(Base, Versioned, Timestamped):
    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", create_type=False), nullable=False, default=OrgRole.member
    )


class InvitationStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    revoked = "revoked"


class OrgInvitation(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "org_invitations"

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


class OrganizationRename(BaseModel):
    """Blank is allowed: the handler answers it, not a 422."""

    name: str = ""


class OrgHandleUpdate(BaseModel):
    handle: str = ""


class OrgTimezoneUpdate(BaseModel):
    timezone: str = ""


class MemberRoleUpdate(BaseModel):
    role: OrgRole


class InvitationCreate(BaseModel):
    email: str = ""


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
    user_id: uuid.UUID
    role: OrgRole


class MemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    role: OrgRole
    created_at: datetime


class OverviewCard(BaseModel):
    key: str
    title: str
    data: dict[str, Any]
