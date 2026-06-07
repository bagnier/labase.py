import uuid
from datetime import datetime

from sqlmodel import Field, SQLModel

from app.shared.utils import utcnow


class Profile(SQLModel, table=True):
    __tablename__ = "profiles"  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    auth_user_id: uuid.UUID = Field(unique=True, index=True)
    email: str = Field(index=True)
    display_name: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ProfileCreate(SQLModel):
    auth_user_id: uuid.UUID
    email: str
    display_name: str | None = None


class ProfileUpdate(SQLModel):
    display_name: str | None = None
