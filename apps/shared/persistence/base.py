"""Declarative base and reusable ORM column mixins, composed by each context's models."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from apps.shared import clock

# Postgres' own auto-naming, spelled out — so a constraint the ORM declares and the same constraint
# written in a migration land on the very same name, by construction rather than by vigilance.
# SQLAlchemy issues no DDL here (the schema is versioned as plain SQL under
# ``supabase/migrations/``), so this is what keeps the two halves able to talk about one object;
# ``tests/test_schema_parity.py`` is what checks they still do.
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
    """A UUIDv7 primary key: time-ordered, so a pk doubles as the monotonic cursor the append-only
    trails read on.

    Generated Python-side on the ORM write path, while the column mirrors ``default
    public.uuidv7()`` for raw and PostgREST inserts. Security tokens are the exception and keep
    uuid4 — unguessable, with no timestamp to read off them.
    """

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

    @declared_attr.directive
    def __mapper_args__(cls):
        return {"version_id_col": cls.version}


class Created:
    """Birth stamp alone — for the append-only tables, where a row is never updated."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )


class Timestamped(Created):
    """Birth and last-touch stamps; ``updated_at`` is also maintained by a DB trigger, so a
    write through PostgREST or psql is stamped exactly like a write through the ORM."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: clock.now()
    )
