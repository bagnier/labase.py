"""Log line names: never a fact's kind (the Timeline tells them apart by source), and prefixed
only by their own app, or the line would outlive another app's deletion.
"""

import ast
import re
from pathlib import Path

import apps.main  # noqa: F401 — fills the catalog
from apps.shared.events.catalog import catalog

_APPS = Path(__file__).resolve().parents[2] / "apps"
_LEVELS = {"debug", "info", "warning", "error", "exception"}
_A_LOGGER = re.compile(r"(self\.)?_?log(ger)?")

_WRITE_PATH = ("shared/events/bus.py", "shared/events/repository.py")

# The write path's two degradations (a name not pinned, a secret masked), not the action.
_THE_WRITE_PATH_SAYS = {"business_event.names_unpinned", "business_event.secret_field_masked"}


def is_a_logger(receiver: ast.expr) -> bool:
    """By the receiver's name: a logger may be a global, a parameter or a field."""
    return _A_LOGGER.fullmatch(ast.unparse(receiver)) is not None


def _log_sites() -> set[tuple[str, str, str]]:
    """``(context, name, file)`` per log call under ``apps/``."""
    return {
        (path.relative_to(_APPS).parts[0], node.args[0].value, path.relative_to(_APPS).as_posix())
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LEVELS
        and is_a_logger(node.func.value)
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _contexts() -> set[str]:
    return {path.name for path in _APPS.iterdir() if (path / "__init__.py").exists()}


def test_no_log_line_spells_a_business_event_kind():
    said_twice = {name for _, name, _ in _log_sites()} & set(catalog.kinds())

    assert said_twice == set()


def test_the_emit_path_says_nothing_of_its_own():
    """Only the two degradations in `_THE_WRITE_PATH_SAYS`."""
    said = {name for _, name, file in _log_sites() if file in _WRITE_PATH}

    assert said == _THE_WRITE_PATH_SAYS


def test_no_context_writes_a_line_under_another_apps_name():
    contexts = _contexts()
    strays = {
        f"{context} writes {name}"
        for context, name, _ in _log_sites()
        if (claimed := name.split(".")[0]) in contexts and claimed != context
    }

    assert strays == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: a walk matching nothing would make them vacuous.
    assert len(_log_sites()) > 50
