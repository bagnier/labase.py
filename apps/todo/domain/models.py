import uuid

from pydantic import BaseModel, ConfigDict
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


class TodoCreate(BaseModel):
    title: str


class TodoTick(BaseModel):
    """The checkbox: ``done`` alone."""

    done: bool


class TodoEdit(BaseModel):
    """The inline edit form: ``title`` alone."""

    title: str


# One PATCH route, two forms: one body or the other, never two optionals.
TodoPatch = TodoTick | TodoEdit


class TodoMove(BaseModel):
    """Above ``above_id``, or last."""

    above_id: uuid.UUID | None = None


class TodoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    done: bool
    position: int
