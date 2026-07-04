import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class OrgFile(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "org_files"

    user_id: Mapped[uuid.UUID]
    filename: Mapped[str] = mapped_column(String)
    storage_path: Mapped[str] = mapped_column(String)
    content_type: Mapped[str] = mapped_column(String, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(default=0)
    uploader_email: Mapped[str] = mapped_column(String, default="")


class OrgFileShareToken(Base):
    __tablename__ = "org_file_share_tokens"

    token: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("org_files.id"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class OrgFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    uploader_email: str
    created_at: datetime
