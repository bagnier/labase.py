"""Create or remove an isolated git worktree wired to its own Supabase schema/bucket.

A worktree gets its own Postgres schema (``wt_<name>`` for dev, ``wt_<name>_test`` for
tests), its own Storage buckets (``org-files-<name>[-test]``) and its own app port — all
on the *single* shared local Supabase stack. DB and files are isolated; auth (GoTrue) is
shared, with the worktree's dev user namespaced by email.

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

ROOT = Path(__file__).resolve().parent.parent
WORKTREES = ROOT / "worktrees"
# Symlinked from the main checkout so a worktree skips `npm install` (static/ is built
# per-worktree by `make dev`, and holds tracked sources, so it is not linked).
SHARED_LINKS = ["node_modules"]


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def _app_port(name: str) -> int:
    """Deterministic app port in 8001..8099 derived from the worktree name."""
    return 8001 + zlib.crc32(name.encode()) % 99


def _write_env(src: Path, dst: Path, overrides: dict[str, str]) -> None:
    lines = src.read_text().splitlines() if src.exists() else []
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=", line)
        if m and m.group(1) in overrides:
            key = m.group(1)
            out.append(f"{key}={overrides[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, val in overrides.items():
        if key not in seen:
            out.append(f"{key}={val}")
    dst.write_text("\n".join(out) + "\n")


def create(name: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", name):
        sys.exit("Worktree name must match [a-z][a-z0-9_-]* (e.g. 'calendar').")
    schema = "wt_" + name.replace("-", "_")
    path = WORKTREES / name
    port = _app_port(name)
    dev_bucket = f"org-files-{name}"
    test_bucket = f"org-files-{name}-test"
    dev_email = f"{name}@labase.dev"

    WORKTREES.mkdir(exist_ok=True)
    if path.exists():
        sys.exit(f"{path} already exists.")

    # Branch: reuse if it exists, else create from current HEAD.
    branches = _run(
        ["git", "branch", "--list", name], cwd=ROOT, capture_output=True, text=True
    ).stdout
    add = ["git", "worktree", "add"]
    add += [str(path), name] if branches.strip() else [str(path), "-b", name]
    _run(add, cwd=ROOT)

    # Per-worktree env files (cloned from the main checkout, with isolation overrides).
    _write_env(
        ROOT / ".env",
        path / ".env",
        {
            "SUPABASE_DATABASE_SCHEMA": schema,
            "SUPABASE_STORAGE_BUCKET": dev_bucket,
            "APP_PORT": str(port),
        },
    )
    _write_env(
        ROOT / ".env.test",
        path / ".env.test",
        {
            "SUPABASE_DATABASE_SCHEMA": f"{schema}_test",
            "SUPABASE_STORAGE_BUCKET": test_bucket,
        },
    )

    # Reuse built assets / node_modules from the main checkout (deps stay per-worktree via uv sync).
    for link in SHARED_LINKS:
        target = ROOT / link
        if target.exists():
            (path / link).symlink_to(target)
    _run(["uv", "sync", "--all-groups"], cwd=path)

    # Provision dev + test schemas/buckets on the shared Supabase. Tooling runs from the
    # main checkout (canonical scripts/config) against the worktree's env file — the
    # worktree's own branch checkout may predate this infrastructure.
    for env_file in (".env", ".env.test"):
        _run(
            ["uv", "run", "python", str(ROOT / "scripts" / "provision_schema.py"), "--reset"],
            cwd=ROOT,
            env=_py_env(path / env_file),
        )
    # Seed a namespaced dev user/org into the dev schema. seed runs host-side, so the
    # Docker-only host.docker.internal must become localhost (env vars override the env file).
    _run(
        ["uv", "run", "python", str(ROOT / "scripts" / "seed.py"), "--email", dev_email],
        cwd=ROOT,
        env={**_py_env(path / ".env"), **_host_overrides(path / ".env")},
    )

    print(
        f"\nWorktree '{name}' ready:\n"
        f"  path     {path}\n"
        f"  schema   {schema} (dev) / {schema}_test (test)\n"
        f"  buckets  {dev_bucket} / {test_bucket}\n"
        f"  app port {port}\n"
        f"  dev user {dev_email} / Devpass123!\n\n"
        f"  cd {path} && make dev   # → http://localhost:{port}\n"
    )


def remove(name: str) -> None:
    path = WORKTREES / name
    # Drop schemas + buckets (run from the worktree so ENV_FILE resolves its DB settings).
    if path.exists():
        for env_file, bucket in (
            (".env", f"org-files-{name}"),
            (".env.test", f"org-files-{name}-test"),
        ):
            subprocess.run(
                [
                    "uv",
                    "run",
                    "python",
                    str(ROOT / "scripts" / "provision_schema.py"),
                    "--drop",
                    "--bucket",
                    bucket,
                ],
                cwd=ROOT,
                env=_py_env(path / env_file),
            )
    _run(["git", "worktree", "remove", "--force", str(path)], cwd=ROOT)
    subprocess.run(["git", "branch", "-D", name], cwd=ROOT)
    print(f"Removed worktree '{name}', its schemas and buckets.")


def _py_env(env_file: Path) -> dict[str, str]:
    """Env for running main-repo tooling against a worktree's env file (absolute ENV_FILE)."""
    return {**os.environ, "ENV_FILE": str(env_file), "PYTHONPATH": str(ROOT)}


def _host_overrides(env_file: Path) -> dict[str, str]:
    """Host-reachable variants of the URL/DB settings (host.docker.internal → localhost)
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
            out[m.group(1)] = m.group(2).replace("host.docker.internal", "localhost")
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
