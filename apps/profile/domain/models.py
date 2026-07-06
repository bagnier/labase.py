import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, UUIDPk, Versioned


class Profile(Base, UUIDPk, Versioned, Timestamped):
    __tablename__ = "profiles"
    __table_args__ = (
        Index("ix_profiles_auth_user_id", "auth_user_id", unique=True),
        Index("ix_profiles_email", "email"),
    )

    auth_user_id: Mapped[uuid.UUID]
    email: Mapped[str] = mapped_column(String)
    handle: Mapped[str | None]
    avatar_path: Mapped[str | None]


class ProfileCreate(BaseModel):
    auth_user_id: uuid.UUID
    email: str
    handle: str | None = None


class ProfileUpdate(BaseModel):
    handle: str | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    auth_user_id: uuid.UUID
    email: str
    handle: str | None
    avatar_path: str | None = None
