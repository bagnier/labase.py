"""Upgrade uv dependencies: relax pins, resolve, re-pin, report changes."""

import re
import sys
from pathlib import Path

# Not ``/tmp``, where anyone can preempt a predictable name.
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
    """Re-pin to the resolved versions. The lock keys names without extras:
    `sqlalchemy[asyncio]` is looked up as `sqlalchemy`."""

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
