import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel

from app.shared.utils import utcnow


class TodoItem(SQLModel, table=True):
    __tablename__ = "todos"  # type: ignore[assignment]

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID
    org_id: uuid.UUID = Field(foreign_key="organizations.id")
    title: str
    done: bool = False
    position: int = 0
    created_at: Optional[datetime] = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class TodoCreate(SQLModel):
    title: str


class TodoRead(SQLModel):
    id: uuid.UUID
    title: str
    done: bool
    position: int
