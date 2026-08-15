"""Upgrade uv dependencies: relax pins, resolve, re-pin, report changes."""

import re
import sys
from pathlib import Path

# Backups live under .cache/ like every other scratch artefact here (pytest, ruff, coverage),
# not in the world-writable /tmp where a predictable name is anyone's to preempt.
BAK = Path(".cache/upgrade")
LOCK_BAK = BAK / "uv.lock.bak"
TOML_BAK = BAK / "pyproject.toml.bak"
LOCK = Path("uv.lock")
TOML = Path("pyproject.toml")


def parse_lock(path: Path) -> dict[str, str]:
    text = path.read_text()
    return {m[1]: m[2] for m in re.finditer(r'name = "(.+?)"\nversion = "(.+?)"', text)}


def relax_pins() -> None:
    TOML.write_text(re.sub(r'==([\d.]+)"', '"', TOML.read_text()))


def repin(content: str, resolved: dict[str, str]) -> str:
    """Write the resolved versions back onto the original pins, extras included.

    The lock keys names normalized (lowercase, no extras), so `sqlalchemy[asyncio]`
    is looked up as `sqlalchemy` — miss it and pyproject silently keeps the old pin.
    """

    def resolve(m: re.Match[str]) -> str:
        name, extras, pinned = m.group(1), m.group(2) or "", m.group(3)
        return f'"{name}{extras}=={resolved.get(name.lower(), pinned)}"'

    return re.sub(r'"([A-Za-z0-9_.-]+)(\[[A-Za-z0-9_,.-]+\])?==([\d.]+)"', resolve, content)


def repin_and_report() -> None:
    old, new = parse_lock(LOCK_BAK), parse_lock(LOCK)
    changed = [(k, old[k], new[k]) for k in old if k in new and old[k] != new[k]]
    if changed:
        for k, o, n in sorted(changed):
            print(f"  {k}: {o} → {n}")
    else:
        print("  Nothing to upgrade.")

    TOML.write_text(repin(TOML_BAK.read_text(), new))


if __name__ == "__main__":
    {"relax": relax_pins, "repin": repin_and_report}[sys.argv[1]]()
