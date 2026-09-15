"""Create or remove an isolated git worktree wired to its own Supabase schema/bucket and test stack.

For dev, a worktree gets its own Postgres schema (``wt_<name>``), Storage bucket
(``org-files-<name>``) and app port on the dev stack, whose auth (GoTrue) it shares — the dev
user is namespaced by email. Its tests run on a stack of their own (``labase-<name>-test``,
scripts/test_stack.py), on the port block its ``.env.test`` names.

Usage:
    uv run python scripts/worktree.py create <name>
    uv run python scripts/worktree.py remove <name>
"""

import argparse
import os
import re
import subprocess
import sys
import zlib
from pathlib import Path

from scripts.envfile import merge_env
from scripts.test_stack import project_id

ROOT = Path(__file__).resolve().parent.parent
WORKTREES = ROOT / "worktrees"
# Symlinked from the main checkout so a worktree skips ``npm install``. ``static/`` is not linked:
# it is built per-worktree by ``make dev`` and holds tracked sources.
SHARED_LINKS = ["node_modules"]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def _app_port(name: str) -> int:
    """Deterministic app port in 8001..8099 derived from the worktree name."""
    return 8001 + zlib.crc32(name.encode()) % 99


def test_block_base(name: str) -> int:
    """First port of the worktree's test stack block, 54500-59400: the main checkout's committed
    ``.env.test`` holds 544xx."""
    return 54500 + zlib.crc32(name.encode()) % 50 * 100


def test_stack_settings(base: int) -> dict[str, str]:
    """``.env.test`` overrides pointing the suite at the block's stack — on the CLI's own offsets
    (21 api, 22 db, 24 mail catcher, 25 its SMTP)."""
    db_url = f"postgresql+asyncpg://postgres:postgres@127.0.0.1:{base + 22}/postgres"
    return {
        "SUPABASE_API_URL": f"http://127.0.0.1:{base + 21}",
        "SUPABASE_DATABASE_USER_URL": db_url,
        "SUPABASE_DATABASE_ADMIN_URL": db_url,
        "MAILPIT_URL": f"http://127.0.0.1:{base + 24}",
        "SMTP_PORT": str(base + 25),
    }


def create(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        sys.exit("Worktree name must match [a-z][a-z0-9_-]* (e.g. 'calendar').")
    schema = "wt_" + name.replace("-", "_")
    path = WORKTREES / name
    port = _app_port(name)
    dev_bucket = f"org-files-{name}"
    test_base = test_block_base(name)
    dev_email = f"{name}@labase.dev"

    WORKTREES.mkdir(exist_ok=True)
    if path.exists():
        sys.exit(f"{path} already exists.")

    branches = _run(
        ["git", "branch", "--list", name], cwd=ROOT, capture_output=True, text=True
    ).stdout
    add = ["git", "worktree", "add"]
    add += [str(path), name] if branches.strip() else [str(path), "-b", name]
    _run(add, cwd=ROOT)

    # Per-worktree env files (cloned from the main checkout, with isolation overrides).
    merge_env(
        ROOT / ".env",
        path / ".env",
        {
            "SUPABASE_DATABASE_SCHEMA": schema,
            "SUPABASE_STORAGE_BUCKET": dev_bucket,
            "APP_PORT": str(port),
        },
    )
    merge_env(ROOT / ".env.test", path / ".env.test", test_stack_settings(test_base))

    # Reuse built assets / node_modules from the main checkout (deps stay per-worktree via uv sync).
    for link in SHARED_LINKS:
        target = ROOT / link
        if target.exists():
            (path / link).symlink_to(target)
    _run(["uv", "sync", "--all-groups"], cwd=path)

    # Provision the dev schema/bucket on the dev stack; the test schema lands on the worktree's
    # own stack, started by its first `make test`. Tooling runs from the main checkout
    # (canonical scripts/config) against the worktree's env file — the worktree's own branch
    # checkout may predate this infrastructure.
    _run(
        ["uv", "run", "python", str(ROOT / "scripts" / "provision_schema.py"), "--reset"],
        cwd=ROOT,
        env=_py_env(path / ".env"),
    )
    # Seed a namespaced dev user/org into the dev schema. seed runs host-side, so the
    # Docker-only host.docker.internal must become 127.0.0.1 (env vars override the env file).
    _run(
        ["uv", "run", "python", str(ROOT / "scripts" / "seed.py"), "--email", dev_email],
        cwd=ROOT,
        env={**_py_env(path / ".env"), **_host_overrides(path / ".env")},
    )

    print(
        f"\nWorktree '{name}' ready:\n"
        f"  path     {path}\n"
        f"  schema   {schema} (dev stack)\n"
        f"  bucket   {dev_bucket}\n"
        f"  tests    {project_id(name)} (api :{test_base + 21}, `make test-stack`)\n"
        f"  app port {port}\n"
        f"  dev user {dev_email} / Devpass123!\n\n"
        f"  cd {path} && make dev   # → http://localhost:{port}\n"
    )


def remove(name: str) -> None:
    path = WORKTREES / name
    # Drop the dev schema + bucket, then the worktree's test stack with its volumes (run from the
    # worktree, whose directory name is the stack's). Best-effort teardown: a schema or a stack
    # already gone is not a failure.
    if path.exists():
        subprocess.run(
            [
                "uv",
                "run",
                "python",
                str(ROOT / "scripts" / "provision_schema.py"),
                "--drop",
                "--bucket",
                f"org-files-{name}",
            ],
            cwd=ROOT,
            env=_py_env(path / ".env"),
            check=False,
        )
        subprocess.run(
            ["uv", "run", "python", str(ROOT / "scripts" / "test_stack.py"), "stop"],
            cwd=path,
            env=_py_env(path / ".env.test"),
            check=False,
        )
    _run(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT)
    subprocess.run(["git", "branch", "-D", name], cwd=ROOT, check=False)  # may not exist
    print(f"Removed worktree '{name}', its dev schema, bucket and test stack.")


def _py_env(env_file: Path) -> dict[str, str]:
    """Env for running main-repo tooling against a worktree's env file (absolute ENV_FILE)."""
    return {**os.environ, "ENV_FILE": str(env_file), "PYTHONPATH": str(ROOT)}


def _host_overrides(env_file: Path) -> dict[str, str]:
    """Host-reachable variants of the URL/DB settings (host.docker.internal → 127.0.0.1)
    for tooling that connects from the host rather than the Docker network."""
    keys = {
        "SUPABASE_API_URL",
        "SUPABASE_STORAGE_URL",
        "SUPABASE_DATABASE_USER_URL",
        "SUPABASE_DATABASE_ADMIN_URL",
    }
    out: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        m = re.match(r"\s*([A-Z_]+)\s*=\s*(.*)", line)
        if m and m.group(1) in keys:
            out[m.group(1)] = m.group(2).replace("host.docker.internal", "127.0.0.1")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("create", "remove"):
        p = sub.add_parser(action)
        p.add_argument("name")
    args = parser.parse_args()
    (create if args.action == "create" else remove)(args.name)


if __name__ == "__main__":
    main()
