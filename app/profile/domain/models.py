import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.persistence.base import Base


class Profile(Base):
    __tablename__ = "profiles"
    __table_args__ = (
        Index("ix_profiles_auth_user_id", "auth_user_id", unique=True),
        Index("ix_profiles_email", "email"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    auth_user_id: Mapped[uuid.UUID]
    email: Mapped[str] = mapped_column(String)
    display_name: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=clock.now)


class ProfileCreate(BaseModel):
    auth_user_id: uuid.UUID
    email: str
    display_name: str | None = None


class ProfileUpdate(BaseModel):
    display_name: str | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    auth_user_id: uuid.UUID
    email: str
    display_name: str | None
