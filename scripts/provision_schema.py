"""Provision an isolated app schema (+ Storage bucket) inside the shared local Supabase.

A worktree gets its own Postgres *schema* (cloned from the finished ``public`` schema)
and its own Storage *bucket*, so its DB/files are isolated without spinning a second
Supabase stack. Auth (GoTrue / ``auth.users``) stays shared — isolation there is logical
(per-worktree email namespacing + a per-schema signup trigger).

Mechanism: ``pg_dump`` the live ``public`` schema (structure only — it already reflects
every migration), rewrite ``public.`` → ``<schema>.``, restore into the target schema,
then recreate the three cross-schema bits a public-only dump can't carry:
the ``auth.users`` signup trigger, the Storage bucket row, and its RLS policies.

Usage:
    uv run python scripts/provision_schema.py --schema wt_demo --bucket org-files-demo
    uv run python scripts/provision_schema.py --schema test --bucket org-files-test --reset
"""

import argparse
import re
import subprocess
import sys

from apps.shared.settings.env import get_technical_settings


def _db_container() -> str:
    """Name of the local Supabase Postgres container (shared by all worktrees)."""
    out = subprocess.run(
        ["docker", "ps", "--format", "{{.Names}}", "--filter", "name=supabase_db"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    if not out:
        sys.exit("No running supabase_db container found — run `make db-start` first.")
    return out[0]


def _psql(container: str, sql: str, *, database: str = "postgres") -> None:
    proc = subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            database,
        ],
        input=sql,
        capture_output=True,
        text=True,
        check=False,  # the returncode is read right below, to surface psql's stderr
    )
    if proc.returncode != 0:
        sys.exit(f"psql failed:\n{proc.stderr}")


def _query(container: str, sql: str) -> str:
    return subprocess.run(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-tAqX",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-c",
            sql,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _dump_public(container: str) -> str:
    return subprocess.run(
        [
            "docker",
            "exec",
            container,
            "pg_dump",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "--schema=public",
            "--schema-only",
            "--no-owner",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _rewrite(dump: str, schema: str) -> str:
    """Rewrite a public-schema dump to target ``schema``. Everything is schema-qualified,
    so two substitutions suffice; ``auth.`` / ``storage.`` / ``test.`` refs stay untouched."""
    # Drop ALTER DEFAULT PRIVILEGES (only affect future objects; some target roles
    # postgres can't act for, e.g. supabase_admin) and the standard-schema comment.
    lines = [
        ln
        for ln in dump.splitlines()
        if not ln.startswith("ALTER DEFAULT PRIVILEGES") and not ln.startswith("COMMENT ON SCHEMA")
    ]
    dump = "\n".join(lines)
    dump = dump.replace("public.", f"{schema}.")
    return dump.replace("SCHEMA public", f"SCHEMA {schema}")  # CREATE / GRANT ... ON SCHEMA


def _storage_and_trigger_sql(schema: str, bucket: str) -> str:
    actions = [
        ("select", "using"),
        ("insert", "with check"),
        ("update", "using"),
        ("delete", "using"),
    ]
    policies = "\n".join(
        f'drop policy if exists "{bucket}: org members {act}" on storage.objects;\n'
        f'create policy "{bucket}: org members {act}" on storage.objects for {act}\n'
        f"  {clause} (bucket_id = '{bucket}'\n"
        f"    and (storage.foldername(name))[1]::uuid in (select {schema}.user_org_ids()));"
        for act, clause in actions
    )
    return f"""
-- Per-schema signup trigger on the shared auth.users (uniquely named so worktrees coexist).
drop trigger if exists on_auth_user_created__{schema} on auth.users;
create trigger on_auth_user_created__{schema}
  after insert on auth.users
  for each row execute procedure {schema}.handle_new_user();

-- Storage bucket + RLS policies scoped to this schema's memberships.
insert into storage.buckets (id, name, public, file_size_limit)
  values ('{bucket}', '{bucket}', false, 52428800)
  on conflict (id) do nothing;
{policies}
"""


def provision(schema: str, bucket: str, *, reset: bool) -> None:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
        sys.exit(f"Invalid schema name: {schema!r}")
    container = _db_container()

    exists = _query(
        container, f"select 1 from information_schema.schemata where schema_name = '{schema}'"
    )
    has_tables = exists and _query(
        container, f"select count(*) from information_schema.tables where table_schema = '{schema}'"
    ) not in ("", "0")
    if has_tables and not reset:
        print(f"Schema {schema} already provisioned (use --reset to rebuild). Refreshing bucket.")
        _psql(container, _storage_and_trigger_sql(schema, bucket))
        return

    dump = _rewrite(_dump_public(container), schema)
    extras = _storage_and_trigger_sql(schema, bucket)
    sql = f"drop schema if exists {schema} cascade;\n{dump}\n{extras}"
    _psql(container, sql)
    print(f"Provisioned schema '{schema}' + bucket '{bucket}'.")


def deprovision(schema: str, bucket: str) -> None:
    container = _db_container()
    _psql(
        container,
        f"drop trigger if exists on_auth_user_created__{schema} on auth.users;\n"
        f"drop schema if exists {schema} cascade;\n"
        # Bypass storage.protect_delete() guard (superuser only) to remove the bucket.
        "set session_replication_role = replica;\n"
        f"delete from storage.objects where bucket_id = '{bucket}';\n"
        f"delete from storage.buckets where id = '{bucket}';\n"
        "set session_replication_role = origin;",
    )
    print(f"Dropped schema '{schema}' + bucket '{bucket}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--schema", default="", help="defaults to SUPABASE_DATABASE_SCHEMA from the env file"
    )
    parser.add_argument("--bucket", default="", help="defaults to SUPABASE_STORAGE_BUCKET")
    parser.add_argument(
        "--reset", action="store_true", help="drop and rebuild the schema structure"
    )
    parser.add_argument("--drop", action="store_true", help="deprovision (drop schema + bucket)")
    args = parser.parse_args()
    settings = get_technical_settings()
    args.schema = args.schema or settings.supabase_database_schema
    bucket = args.bucket or settings.supabase_storage_bucket
    if args.schema == "public":
        sys.exit("Refusing to provision/drop the 'public' schema.")
    if args.drop:
        deprovision(args.schema, bucket)
    else:
        provision(args.schema, bucket, reset=args.reset)


if __name__ == "__main__":
    main()
