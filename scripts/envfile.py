"""Env-file merging: write the given keys, keep every other line."""

import os
import re
from pathlib import Path

# Settings a Docker-shaped `.env` points at `host.docker.internal`, which only the container
# resolves; host-side scripts reach them at 127.0.0.1.
_HOST_ONLY_SETTINGS = {
    "SUPABASE_API_URL",
    "SUPABASE_STORAGE_URL",
    "SUPABASE_DATABASE_USER_URL",
    "SUPABASE_DATABASE_ADMIN_URL",
    "SMTP_HOST",
}


def host_reachable_overrides(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}
    out: dict[str, str] = {}
    for line in env_file.read_text().splitlines():
        m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)", line)
        if m and m.group(1) in _HOST_ONLY_SETTINGS and "host.docker.internal" in m.group(2):
            out[m.group(1)] = m.group(2).replace("host.docker.internal", "127.0.0.1")
    return out


def apply_host_overrides(env_file: Path) -> None:
    """Put `env_file`'s Docker-only settings in the environment, host-reachable, unless already
    set. Call from the entry point, never at import: tests import these modules."""
    for key, value in host_reachable_overrides(env_file).items():
        os.environ.setdefault(key, value)


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
