import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from app.shared.utils import utcnow


class OrgFile(SQLModel, table=True):
    __tablename__ = "org_files"  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    org_id: uuid.UUID = Field(foreign_key="organizations.id")
    user_id: uuid.UUID
    filename: str
    storage_path: str
    content_type: str = "application/octet-stream"
    size_bytes: int = 0
    created_at: Optional[datetime] = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class OrgFileRead(SQLModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime
