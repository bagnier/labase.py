import uuid
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    auth_user_id: uuid.UUID = Field(unique=True, index=True)
    email: str = Field(index=True)
    display_name: str | None = None
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ProfileCreate(SQLModel):
    auth_user_id: uuid.UUID
    email: str
    display_name: str | None = None


class ProfileUpdate(SQLModel):
    display_name: str | None = None
