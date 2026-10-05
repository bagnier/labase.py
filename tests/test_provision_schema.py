"""A schema cloned by scripts/provision_schema.py matches ``public``, including what it adds by
hand outside the dump (the bucket, its policies, the signup trigger).
"""

import os
from collections.abc import Iterator

import pytest

from scripts import provision_schema as ps

GUARD_SCHEMA = "wt_guard"
GUARD_BUCKET = "org-files-guard"

# Run schemas outlive their run for inspection; this test uses its own, live pid.
LIVE_SCHEMA = f"test_{os.getpid()}"
LIVE_BUCKET = f"org-files-test-{os.getpid()}"
# Above any Linux pid (2^22 at most): never alive.
DEAD_PID = 4_194_304 + 1
DEAD_SCHEMA = f"test_{DEAD_PID}"
DEAD_BUCKET = f"org-files-test-{DEAD_PID}"


@pytest.fixture
def guard_schema() -> Iterator[str]:
    ps.provision(GUARD_SCHEMA, GUARD_BUCKET, reset=True)
    yield GUARD_SCHEMA
    ps.deprovision(GUARD_SCHEMA, GUARD_BUCKET)


@pytest.fixture
def live_run_schema() -> Iterator[str]:
    yield LIVE_SCHEMA
    ps.deprovision(LIVE_SCHEMA, LIVE_BUCKET)


def test_db_port_is_the_host_port_of_the_database_url():
    url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:22622/postgres"

    assert ps.db_port(url) == 22622


def _count(container: str, sql: str) -> str:
    return ps._query(container, sql)


def _schema_count(container: str, schema: str) -> str:
    sql = f"select count(*) from information_schema.schemata where schema_name = '{schema}'"
    return _count(container, sql)


def test_clone_matches_public(guard_schema: str) -> None:
    c = ps._db_container()

    public_tables = _count(
        c, "select count(*) from information_schema.tables where table_schema = 'public'"
    )
    clone_tables = _count(
        c, f"select count(*) from information_schema.tables where table_schema = '{GUARD_SCHEMA}'"
    )
    assert clone_tables == public_tables != "0"

    # The SECURITY DEFINER helper Storage RLS needs.
    assert (
        _count(
            c,
            "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            f"where n.nspname = '{GUARD_SCHEMA}' and p.proname = 'user_org_ids'",
        )
        == "1"
    )

    # The hand-written part, where drift happens:
    assert _count(c, f"select count(*) from storage.buckets where id = '{GUARD_BUCKET}'") == "1"
    assert (
        _count(
            c,
            "select count(*) from pg_trigger "
            f"where tgname = 'on_auth_user_created__{GUARD_SCHEMA}'",
        )
        == "1"
    )
    # As many policies as ``org-files``.
    public_policies = _count(
        c, "select count(*) from pg_policies where policyname like 'org-files: %'"
    )
    clone_policies = _count(
        c, f"select count(*) from pg_policies where policyname like '{GUARD_BUCKET}: %'"
    )
    assert clone_policies == public_policies != "0"


def test_provision_drops_a_run_schema_whose_pid_has_exited(live_run_schema: str) -> None:
    ps.provision(DEAD_SCHEMA, DEAD_BUCKET, reset=True)

    ps.provision(live_run_schema, LIVE_BUCKET, reset=True)

    c = ps._db_container()
    assert _schema_count(c, DEAD_SCHEMA) == "0"


def test_provision_keeps_a_run_schema_whose_pid_is_alive(live_run_schema: str) -> None:
    ps.provision(live_run_schema, LIVE_BUCKET, reset=True)
    other_schema, other_bucket = "test_4194306", "org-files-test-4194306"

    ps.provision(other_schema, other_bucket, reset=True)  # its sweep must skip LIVE_SCHEMA
    ps.deprovision(other_schema, other_bucket)

    c = ps._db_container()
    assert _schema_count(c, live_run_schema) == "1"
