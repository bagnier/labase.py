"""The declarative base and the column mixins every context's models compose."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from apps.shared import clock

# Postgres's own default names, so the ORM and the SQL migrations name a constraint alike.
NAMING_CONVENTION = {
    "pk": "%(table_name)s_pkey",
    "uq": "%(table_name)s_%(column_0_N_name)s_key",
    "fk": "%(table_name)s_%(column_0_N_name)s_fkey",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "ix": "%(table_name)s_%(column_0_N_name)s_idx",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPk:
    """A UUIDv7 primary key (AGENTS: every key is a UUIDv7, every token a UUIDv4), minted here on
    ORM writes and by the column default ``public.uuidv7()`` elsewhere."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid7)


class OrgScoped:
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))


class Positioned:
    """Managed by `PositionedRepository`."""

    position: Mapped[int] = mapped_column(default=0)


class Versioned:
    """Optimistic lock: a stale write raises ``StaleDataError``, answered as a 409."""

    version: Mapped[int] = mapped_column(default=1)

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class Created:
    """For append-only tables."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )


class Timestamped(Created):
    """``updated_at`` is also set by a DB trigger, for writes outside the ORM."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
