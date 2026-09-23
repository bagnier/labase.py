"""Shared env-file merge: write known overrides, preserve every other line untouched."""

import os
import re
from pathlib import Path

# The settings a Docker-shaped `.env` (`make env`) points at `host.docker.internal`, which
# resolves only inside the app container — a host-side script (`make db-seed`, `make preflight`,
# `make backup-storage`, a worktree's seed) reaches the same services at 127.0.0.1 instead.
_HOST_ONLY_SETTINGS = {
    "SUPABASE_API_URL",
    "SUPABASE_STORAGE_URL",
    "SUPABASE_DATABASE_USER_URL",
    "SUPABASE_DATABASE_ADMIN_URL",
}


def host_reachable_overrides(env_file: Path) -> dict[str, str]:
    """The tracked settings whose `env_file` value is Docker-only, rewritten to 127.0.0.1."""
    if not env_file.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", line)
        if m and m.group(1) in _HOST_ONLY_SETTINGS and "host.docker.internal" in m.group(2):
            out[m.group(1)] = m.group(2).replace("host.docker.internal", "127.0.0.1")
    return out


def pending_host_overrides(env_file: Path) -> dict[str, str]:
    """`host_reachable_overrides` not already set in the environment, for the caller to apply
    with `os.environ.update(...)` — an explicit value already set (an operator's own override)
    is left alone."""
    return {k: v for k, v in host_reachable_overrides(env_file).items() if k not in os.environ}


def merge_env(src: Path, dst: Path, overrides: dict[str, str]) -> None:
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
