import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import (
    Base,
    OrgScoped,
    Positioned,
    Timestamped,
    UUIDPk,
    Versioned,
)


class Todo(Base, UUIDPk, OrgScoped, Positioned, Versioned, Timestamped):
    __tablename__ = "todos"

    user_id: Mapped[uuid.UUID]
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)


class TodoCompletionStats(Base):
    """Completions *ever*, per org — bumped by the ``todos_bump_completion`` trigger, in the
    transaction that ticks the task. Nothing in Python writes it; the app only reads."""

    __tablename__ = "todo_completion_stats"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), primary_key=True)
    completed_count: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TodoCreate(BaseModel):
    title: str


class TodoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    done: bool
    position: int
