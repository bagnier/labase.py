import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, DateTime, Enum as SAEnum
from sqlmodel import Field, SQLModel

from app.shared.utils import utcnow


class OrgRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"


class Organization(SQLModel, table=True):
    __tablename__ = "organizations"  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Membership(SQLModel, table=True):
    __tablename__ = "memberships"  # type: ignore[assignment]

    org_id: uuid.UUID = Field(foreign_key="organizations.id", primary_key=True)
    auth_user_id: uuid.UUID = Field(primary_key=True)
    role: OrgRole = Field(
        default=OrgRole.member,
        sa_column=Column(SAEnum(OrgRole, name="org_role", create_type=False), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrganizationCreate(SQLModel):
    name: str


class OrganizationRead(SQLModel):
    id: uuid.UUID
    name: str
    created_at: datetime


class MembershipRead(SQLModel):
    org_id: uuid.UUID
    auth_user_id: uuid.UUID
    role: OrgRole


class OrganizationService(SQLModel):
    """Données agrégées utiles pour un membre : org + son rôle."""

    org: OrganizationRead
    role: OrgRole
    is_active: Optional[bool] = None
