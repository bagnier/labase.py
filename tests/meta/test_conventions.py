"""Conventions the README states as absolutes, checked from the artefact rather than its prose.

Each of these decays one exception at a time — a fourth session dependency, a serial key, a test
module parked next to the router it tests — and no single exception breaks anything the day it
lands. The walks below make the first exception cost an edit here, which is the decision the
README says someone has to make.
"""

import ast
import uuid
from pathlib import Path

import apps.main  # noqa: F401 — mounting every app fills the ORM registry with every model
from apps.shared.persistence.base import Base

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

# The three dependencies the README names — `RlsSession` wraps the first, `AdminSession` the
# third — plus the private substrate the two raw ones share. A fifth entry here is the "real
# decision" the claim's waiver said would announce itself nowhere; now it announces itself here.
_SESSION_PROVIDERS = {
    "apps/auth/infra/session.py::get_rls_session",
    "apps/shared/persistence/database.py::_session",
    "apps/shared/persistence/database.py::get_admin_session",
    "apps/shared/persistence/database.py::get_user_session",
}

# Link and settings tables keep their natural composite keys — a surrogate id on a row that *is*
# its pair would be a second identity to keep unique. The share token is the README's own stated
# exception: a security token stays a random uuid4, unguessable, with no timestamp to read off it.
_NATURAL_COMPOSITE_KEYS = {"app_settings", "memberships", "org_app_settings"}
_RANDOM_TOKEN_KEYS = {"org_file_share_tokens"}


def _python_files(*roots: Path):
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            yield path, str(path.relative_to(_ROOT))


def test_the_session_dependencies_are_exactly_the_three_named():
    """A DB session provider is a function yielding an ``AsyncSession`` — the shape FastAPI
    injects. Enumerated over ``apps/`` so a fourth kind of session cannot appear quietly."""
    providers = {
        f"{relative}::{node.name}"
        for path, relative in _python_files(_APPS)
        if "/tests/" not in relative
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.returns is not None
        and "AsyncGenerator[AsyncSession" in ast.unparse(node.returns)
    }

    assert providers == _SESSION_PROVIDERS


def _key_generator(column) -> object:
    """The Python callable a pk column defaults to — unwrapped, since SQLAlchemy wraps a
    zero-argument callable to feed it the execution context."""
    generate = getattr(column.default, "arg", None)
    return getattr(generate, "__wrapped__", generate)


def test_every_mapped_primary_key_is_a_time_ordered_uuid7():
    """ "Every primary key is a time-ordered UUIDv7" — walked over every mapped table, not proven
    on the mixin alone. The two exception families are frozen above, so a new composite key or a
    new token is an edit here, made on purpose."""
    composite, tokens, strays = set(), set(), set()
    for table in Base.metadata.tables.values():
        keys = list(table.primary_key.columns)
        if len(keys) > 1:
            composite.add(table.name)
        elif _key_generator(keys[0]) is uuid.uuid4:
            tokens.add(table.name)
        elif _key_generator(keys[0]) is not uuid.uuid7:
            strays.add(f"{table.name}.{keys[0].name}")

    assert (composite, tokens, strays) == (_NATURAL_COMPOSITE_KEYS, _RANDOM_TOKEN_KEYS, set())


def test_templates_tests_and_steps_live_with_their_context():
    """The layout half of self-containment: a template, a test or a step module parked outside
    its context is the piece a deletion leaves behind."""
    misplaced = (
        {
            str(path.relative_to(_ROOT))
            for path in list(_APPS.rglob("steps.py")) + list((_ROOT / "tests").rglob("steps.py"))
            if not path.match("apps/*/tests/e2e/steps.py")
        }
        | {
            str(path.relative_to(_ROOT))
            for path in _APPS.rglob("templates")
            if path.is_dir() and not path.match("apps/*/templates")
        }
        | {
            relative
            for path, relative in _python_files(_APPS)
            if path.name.startswith("test_") and "/tests/" not in relative
        }
    )

    assert misplaced == set()


def test_the_layout_walk_actually_finds_the_files():
    # Guards the guard: globs that matched nothing would make the assertion above vacuous.
    steps = list(_APPS.rglob("steps.py"))

    template_roots = [path for path in _APPS.rglob("templates") if path.is_dir()]

    assert (len(steps) > 10, len(template_roots) > 10) == (True, True)
