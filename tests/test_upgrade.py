"""scripts/upgrade.py re-pins every dependency, extras included (`sqlalchemy[asyncio]`): a missed
one would leave pyproject behind the lock.
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
