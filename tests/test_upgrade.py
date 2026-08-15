"""Guard for scripts/upgrade.py's re-pinning step.

`make upgrade` strips every `==` pin, lets uv resolve, then writes the resolved versions
back into pyproject.toml. If the write-back misses a dependency, the lock advances while
pyproject keeps the old pin — the two disagree silently and the next `uv sync` walks the
upgrade back. Dependencies carrying extras (`sqlalchemy[asyncio]`) are the easy miss.
"""

from scripts.upgrade import repin

RESOLVED = {"sqlalchemy": "2.0.52", "pyjwt": "2.14.0", "asyncpg": "0.31.0"}


def test_repin_updates_a_dependency_carrying_extras():
    pinned = 'dependencies = [\n    "sqlalchemy[asyncio]==2.0.50",\n]\n'

    repinned = repin(pinned, RESOLVED)

    assert repinned == 'dependencies = [\n    "sqlalchemy[asyncio]==2.0.52",\n]\n'


def test_repin_matches_the_lock_case_insensitively():
    pinned = 'dependencies = [\n    "PyJWT==2.13.0",\n]\n'

    repinned = repin(pinned, RESOLVED)

    assert repinned == 'dependencies = [\n    "PyJWT==2.14.0",\n]\n'


def test_repin_leaves_a_dependency_the_lock_did_not_move():
    pinned = 'dependencies = [\n    "asyncpg==0.31.0",\n]\n'

    repinned = repin(pinned, RESOLVED)

    assert repinned == 'dependencies = [\n    "asyncpg==0.31.0",\n]\n'
