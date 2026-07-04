import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Mapped, mapped_column

from apps.shared.persistence.base import Base, OrgScoped, Timestamped, UUIDPk, Versioned


class TodoItem(Base, UUIDPk, OrgScoped, Versioned, Timestamped):
    __tablename__ = "todos"

    user_id: Mapped[uuid.UUID]
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(default=0)


class TodoCreate(BaseModel):
    title: str


class TodoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    done: bool
    position: int
