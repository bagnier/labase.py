import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from apps.shared import clock


class Base(DeclarativeBase):
    pass


class UUIDPk:
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class OrgScoped:
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))


class Versioned:
    version: Mapped[int] = mapped_column(default=1)

    @declared_attr
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
