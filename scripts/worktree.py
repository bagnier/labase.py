"""Create or remove an isolated git worktree wired to its own Supabase schema/bucket and test stack.

On the dev stack: a schema (``wt_<name>``), a bucket (``org-files-<name>``) and an app port,
sharing auth. Tests run on a stack of their own (scripts/test_stack.py).

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

from scripts.envfile import host_reachable_overrides, merge_env
from scripts.test_stack import project_id

ROOT = Path(__file__).resolve().parent.parent
WORKTREES = ROOT / "worktrees"
# Symlinked, sparing ``npm install``. Not ``static/``: built per worktree, with tracked sources.
SHARED_LINKS = ["node_modules"]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def _app_port(name: str) -> int:
    """8001..8099, from the name."""
    return 8001 + zlib.crc32(name.encode()) % 99


def test_block_base(name: str) -> int:
    """In 54500-59400, above the main checkout's 544xx."""
    return 54500 + zlib.crc32(name.encode()) % 50 * 100


def test_stack_settings(base: int) -> dict[str, str]:
    """``.env.test`` ports, on the CLI's offsets (21 api, 22 db, 24 mail, 25 SMTP)."""
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

    for link in SHARED_LINKS:
        target = ROOT / link
        if target.exists():
            (path / link).symlink_to(target)
    _run(["uv", "sync", "--all-groups"], cwd=path)

    # The test schema comes with the worktree's first `make test`. Tooling runs from the main
    # checkout: the worktree's branch may predate it.
    _run(
        ["uv", "run", "python", str(ROOT / "scripts" / "provision_schema.py"), "--reset"],
        cwd=ROOT,
        env=_py_env(path / ".env"),
    )
    # Host-side: host.docker.internal becomes 127.0.0.1.
    _run(
        ["uv", "run", "python", str(ROOT / "scripts" / "seed.py"), "--email", dev_email],
        cwd=ROOT,
        env={**_py_env(path / ".env"), **host_reachable_overrides(path / ".env")},
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
    # Best effort: what is already gone is no failure.
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
    subprocess.run(["git", "branch", "-D", name], cwd=ROOT, check=False)
    print(f"Removed worktree '{name}', its dev schema, bucket and test stack.")


def _py_env(env_file: Path) -> dict[str, str]:
    """For main-checkout tooling on a worktree's env file."""
    return {**os.environ, "ENV_FILE": str(env_file), "PYTHONPATH": str(ROOT)}


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
