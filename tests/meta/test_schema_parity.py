"""Parity guard: what the ORM declares and what the database holds must be the same thing.

``Base.metadata`` is a *claim* about the database — its tables, their columns and nullability,
and the names of the indexes and constraints on them. Nothing checks that claim: SQLAlchemy
never issues DDL in this project (the schema is versioned as plain SQL under
``supabase/migrations/``), so a model can declare an index that exists nowhere, or stay silent
about a column that does, and the whole suite still passes. Both drifts were real when this
test was written.

Reads the live schema back and compares. Every model module is imported by glob, so a new
context is covered the day its models land, without anyone remembering this file.
"""

import importlib
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import Enum, text
from sqlalchemy.ext.asyncio import create_async_engine

from apps.shared.persistence.base import Base
from apps.shared.persistence.database import admin_url, search_path_connect_args
from apps.shared.settings.env import get_technical_settings

_EXTRA_MODEL_MODULES = (
    "apps.shared.events.models",
    "apps.shared.settings.store",
    "apps.shared.logs.models",
)


def _import_every_model() -> None:
    """Populate ``Base.metadata`` — a table is only declared once its module is imported."""
    for path in sorted(Path("apps").glob("*/domain/models.py")):
        importlib.import_module(str(path.with_suffix("")).replace("/", "."))
    for module in _EXTRA_MODEL_MODULES:
        importlib.import_module(module)


class LiveSchema:
    def __init__(
        self,
        columns: dict[tuple[str, str], bool],
        relation_names: set[str],
        closed_sets: dict[tuple[str, str], list[str]],
        primary_keys: dict[str, set[str]],
    ) -> None:
        self.columns = columns
        self.relation_names = relation_names
        # Every column typed by a Postgres enum, with the labels it may hold, in order.
        self.closed_sets = closed_sets
        # Every table's primary key columns, by table name.
        self.primary_keys = primary_keys

    @property
    def tables(self) -> set[str]:
        return {table for table, _ in self.columns}


@pytest_asyncio.fixture
async def live_schema() -> LiveSchema:
    settings = get_technical_settings()
    schema = settings.supabase_database_schema
    engine = create_async_engine(
        admin_url(settings), connect_args=search_path_connect_args(settings)
    )
    try:
        async with engine.connect() as conn:
            columns = (
                await conn.execute(
                    text(
                        "select table_name, column_name, is_nullable "
                        "from information_schema.columns where table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            ).all()
            # Indexes and constraints share one namespace here on purpose: a UNIQUE constraint
            # is backed by an index of the same name, and a model may declare either shape.
            relations = (
                await conn.execute(
                    text(
                        "select indexname as name from pg_indexes where schemaname = :schema "
                        "union "
                        "select c.conname from pg_constraint c "
                        "join pg_class t on t.oid = c.conrelid "
                        "join pg_namespace n on n.oid = t.relnamespace "
                        "where n.nspname = :schema"
                    ),
                    {"schema": schema},
                )
            ).all()
            closed_sets = (
                await conn.execute(
                    text(
                        "select c.table_name, c.column_name, "
                        "array_agg(e.enumlabel order by e.enumsortorder) "
                        "from information_schema.columns c "
                        "join pg_namespace n on n.nspname = c.udt_schema "
                        "join pg_type t on t.typnamespace = n.oid and t.typname = c.udt_name "
                        "join pg_enum e on e.enumtypid = t.oid "
                        "where c.table_schema = :schema "
                        "group by c.table_name, c.column_name"
                    ),
                    {"schema": schema},
                )
            ).all()
            primary_keys = (
                await conn.execute(
                    text(
                        "select tc.table_name, kcu.column_name "
                        "from information_schema.table_constraints tc "
                        "join information_schema.key_column_usage kcu "
                        "  on kcu.constraint_name = tc.constraint_name "
                        "  and kcu.table_schema = tc.table_schema "
                        "where tc.constraint_type = 'PRIMARY KEY' and tc.table_schema = :schema"
                    ),
                    {"schema": schema},
                )
            ).all()
    finally:
        await engine.dispose()

    pk_by_table: dict[str, set[str]] = {}
    for table, column in primary_keys:
        pk_by_table.setdefault(table, set()).add(column)

    return LiveSchema(
        columns={(table, column): nullable == "YES" for table, column, nullable in columns},
        relation_names={name for (name,) in relations},
        closed_sets={(table, column): list(labels) for table, column, labels in closed_sets},
        primary_keys=pk_by_table,
    )


@pytest.fixture(autouse=True)
def every_model_imported() -> None:
    _import_every_model()


def test_every_mapped_table_exists_in_the_database(live_schema: LiveSchema) -> None:
    missing = sorted(set(Base.metadata.tables) - live_schema.tables)

    assert missing == []


def test_every_mapped_column_matches_the_database(live_schema: LiveSchema) -> None:
    declared = {
        (table.name, column.name): column.nullable
        for table in Base.metadata.tables.values()
        for column in table.columns
    }

    disagreements = {
        key: {"orm_nullable": nullable, "database": live_schema.columns.get(key, "absent")}
        for key, nullable in declared.items()
        if live_schema.columns.get(key, "absent") != nullable
    }

    assert disagreements == {}


def test_every_mapped_primary_key_matches_the_database(live_schema: LiveSchema) -> None:
    """The ORM and the table must agree on which columns identify a row — the case that exposed
    a mismatch was a table partitioned by range, where Postgres requires the partition column in
    every unique key, but the rule holds for any table a model maps only part of the key of."""
    declared = {
        table.name: {column.name for column in table.primary_key.columns}
        for table in Base.metadata.tables.values()
    }

    disagreements = {
        name: {"orm": columns, "database": live_schema.primary_keys.get(name, set())}
        for name, columns in declared.items()
        if live_schema.primary_keys.get(name, set()) != columns
    }

    assert disagreements == {}


def test_every_declared_index_and_constraint_exists_in_the_database(
    live_schema: LiveSchema,
) -> None:
    declared = {
        str(index.name) for table in Base.metadata.tables.values() for index in table.indexes
    } | {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        # An unnamed constraint (a bare primary key) has nothing to compare against.
        if isinstance(constraint.name, str)
    }

    missing = sorted(name for name in declared if name not in live_schema.relation_names)

    assert missing == []


def test_every_closed_set_column_is_a_python_enum(live_schema: LiveSchema) -> None:
    """ "A constraint the domain must uphold is expressed as a constrained type wherever it can
    be" — a column the database closes over a set of labels is the case where it always can. So
    every such column is mapped through a ``StrEnum`` spelling exactly those labels, in order,
    and a fifth role or a sixth status is a type error before it is a constraint violation. The
    converse holds too: an enum the ORM declares that the database does not close is a check
    Python is keeping alone."""
    declared = {
        (table.name, column.name): [member.value for member in column.type.enum_class]
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, Enum) and column.type.enum_class is not None
    }

    assert declared == live_schema.closed_sets
