"""Drift guard for scripts/provision_schema.py.

The provisioner clones ``public`` via pg_dump, then re-adds three cross-schema bits by
hand (the Storage bucket, its RLS policies, the signup trigger) because a public-only dump
cannot carry them. That hand-written block can silently drift from the migrations — e.g. a
new Storage policy or a second bucket would land in ``public`` but not in a clone. This test
provisions a throwaway schema and asserts the clone is faithful, so drift fails CI loudly.
"""

import os
from collections.abc import Iterator

import pytest

from scripts import provision_schema as ps

GUARD_SCHEMA = "wt_guard"
GUARD_BUCKET = "org-files-guard"

# A per-run schema (test_<pid>) outlives its own `make` invocation on purpose, so a failed
# run stays inspectable — but nothing ever drops one whose pid has since exited, and it is
# recreated with this test's own pid, guaranteed alive for the test's duration.
LIVE_SCHEMA = f"test_{os.getpid()}"
LIVE_BUCKET = f"org-files-test-{os.getpid()}"
# No Linux pid reaches this value (max_pid_max tops out at 2^22), so it can never be alive.
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

    # Tables: the dump must reproduce every public table in the clone.
    public_tables = _count(
        c, "select count(*) from information_schema.tables where table_schema = 'public'"
    )
    clone_tables = _count(
        c, f"select count(*) from information_schema.tables where table_schema = '{GUARD_SCHEMA}'"
    )
    assert clone_tables == public_tables != "0"

    # SECURITY DEFINER helper the Storage RLS depends on must be cloned.
    assert (
        _count(
            c,
            "select count(*) from pg_proc p join pg_namespace n on n.oid = p.pronamespace "
            f"where n.nspname = '{GUARD_SCHEMA}' and p.proname = 'user_org_ids'",
        )
        == "1"
    )

    # Cross-schema block (hand-written) — the actual drift surface:
    assert _count(c, f"select count(*) from storage.buckets where id = '{GUARD_BUCKET}'") == "1"
    assert (
        _count(
            c,
            "select count(*) from pg_trigger "
            f"where tgname = 'on_auth_user_created__{GUARD_SCHEMA}'",
        )
        == "1"
    )
    # Storage policy parity: the clone's bucket must carry the same number of policies as
    # the canonical ``org-files`` bucket. A migration adding a policy without updating
    # provision_schema._storage_and_trigger_sql() trips this.
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

    ps.provision(other_schema, other_bucket, reset=True)  # its own sweep must skip LIVE_SCHEMA
    ps.deprovision(other_schema, other_bucket)

    c = ps._db_container()
    assert _schema_count(c, live_run_schema) == "1"
