"""Declarative base and reusable ORM column mixins, composed by each context's models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from apps.shared import clock


class Base(DeclarativeBase):
    pass


class UUIDPk:
    # UUIDv7: time-ordered, so a pk doubles as a monotonic cursor (the append-only trails order on
    # it). Generated Python-side on the ORM write path; the DB column mirrors `default
    # public.uuidv7()` for raw / PostgREST inserts. Tokens keep uuid4 (unguessable, no timestamp).
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)


class OrgScoped:
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))


class Positioned:
    """Dense 0-based ordering column, managed by `PositionedRepository`."""

    position: Mapped[int] = mapped_column(default=0)


class Versioned:
    """Optimistic-lock version column: a stale concurrent write raises ``StaleDataError``,
    which the shared handler turns into a clean 409."""

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
