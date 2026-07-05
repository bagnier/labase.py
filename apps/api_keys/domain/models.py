import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class ApiKey(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    """An org-scoped machine credential; only its sha256 hash is at rest."""

    __tablename__ = "api_keys"

    created_by: Mapped[uuid.UUID]
    name: Mapped[str]
    prefix: Mapped[str]  # displayable head of the token
    key_hash: Mapped[str]
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreated(ApiKeyRead):
    """Creation response only: the one and only time the secret is readable."""

    secret: str
