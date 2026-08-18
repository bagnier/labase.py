import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Index, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, Timestamped, UUIDPk, Versioned


class Profile(Base, UUIDPk, Versioned, Timestamped):
    __tablename__ = "profiles"
    __table_args__ = (
        UniqueConstraint("user_id"),
        Index("profiles_email_idx", "email"),
        # Partial: the handle is set lazily on first profile access, so several rows may sit at
        # null at once — which a unique *constraint* would forbid.
        Index(
            "profiles_handle_idx",
            "handle",
            unique=True,
            postgresql_where=text("handle is not null"),
        ),
    )

    user_id: Mapped[uuid.UUID]
    email: Mapped[str] = mapped_column(String)
    handle: Mapped[str | None]
    avatar_path: Mapped[str | None]


class ProfileCreate(BaseModel):
    user_id: uuid.UUID
    email: str
    handle: str | None = None


class ProfileUpdate(BaseModel):
    handle: str | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    email: str
    handle: str | None
    avatar_path: str | None = None
