import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.shared import clock
from app.shared.persistence.base import Base


class TodoItem(Base):
    __tablename__ = "todos"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID]
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    title: Mapped[str]
    done: Mapped[bool] = mapped_column(default=False)
    position: Mapped[int] = mapped_column(default=0)
    version: Mapped[int] = mapped_column(default=1)

    __mapper_args__ = {"version_id_col": version}
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )


class TodoCreate(BaseModel):
    title: str


class TodoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    done: bool
    position: int
