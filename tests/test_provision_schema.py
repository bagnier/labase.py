"""Drift guard for scripts/provision_schema.py.

The provisioner clones ``public`` via pg_dump, then re-adds three cross-schema bits by
hand (the Storage bucket, its RLS policies, the signup trigger) because a public-only dump
cannot carry them. That hand-written block can silently drift from the migrations — e.g. a
new Storage policy or a second bucket would land in ``public`` but not in a clone. This test
provisions a throwaway schema and asserts the clone is faithful, so drift fails CI loudly.
"""

import pytest

from scripts import provision_schema as ps

GUARD_SCHEMA = "wt_guard"
GUARD_BUCKET = "org-files-guard"


@pytest.fixture
def guard_schema() -> str:
    ps.provision(GUARD_SCHEMA, GUARD_BUCKET, reset=True)
    yield GUARD_SCHEMA
    ps.deprovision(GUARD_SCHEMA, GUARD_BUCKET)


def _count(container: str, sql: str) -> str:
    return ps._query(container, sql)


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
            f"where n.nspname = '{GUARD_SCHEMA}' and p.proname = 'user_orgs'",
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
