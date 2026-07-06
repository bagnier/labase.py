"""Shared env-file merge: write known overrides, preserve every other line untouched."""

import re
from pathlib import Path


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
