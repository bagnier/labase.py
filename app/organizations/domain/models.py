import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.base import Base
from app.shared.utils import utcnow


class OrgRole(str, Enum):
    owner = "owner"
    member = "member"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str]
    slug: Mapped[str] = mapped_column(default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class Membership(Base):
    __tablename__ = "memberships"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    auth_user_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    role: Mapped[OrgRole] = mapped_column(
        SAEnum(OrgRole, name="org_role", create_type=False), nullable=False, default=OrgRole.member
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


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


class OrganizationService(BaseModel):
    """Données agrégées utiles pour un membre : org + son rôle."""

    org: OrganizationRead
    role: OrgRole
    is_active: Optional[bool] = None
