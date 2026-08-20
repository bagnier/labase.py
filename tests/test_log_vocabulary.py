"""One invariant over the *log line names*: a line never spells a fact, nor claims another app.

``tests/test_event_vocabulary`` pins what the journal says. This pins what the log sink says, and
the rule holding the two apart — because they meet again in the console's Timeline, where a reader
tells a fact from a trace by its **source**, never by re-reading its name. A line spelling
``issues.opened`` would put one wording on both sides of that split: on the journal side something
that happened and correlates, on the technical side something that merely got written.

The second half is the same confusion seen from the app axis, which the Timeline takes from the
*logger*: a shared module writing ``issues.something`` files its line under a context that never
wrote it — and the line then survives deleting that app, which is exactly what the base's
"deleting an app removes every trace of it" promise says cannot happen.

Same shape and same reason as ``test_emit_sites``: these names are string literals at call sites,
so nothing but an AST walk enumerates them.
"""

import ast
from pathlib import Path

import apps.main  # noqa: F401  — mounting every app fills the catalog
from apps.shared.events.catalog import catalog

_APPS = Path(__file__).resolve().parent.parent / "apps"
_LEVELS = {"debug", "info", "warning", "error", "exception"}


def _log_sites() -> set[tuple[str, str]]:
    """Every ``(context, name)`` a ``log.<level>("name", …)`` call declares under ``apps/``, tests
    aside — the context being the package the file lives in (``shared`` for the base itself)."""
    return {
        (path.relative_to(_APPS).parts[0], node.args[0].value)
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _LEVELS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "log"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


def _contexts() -> set[str]:
    return {path.name for path in _APPS.iterdir() if (path / "__init__.py").exists()}


def test_no_log_line_spells_a_business_event_kind():
    """A fact is recorded once, on the journal, and ``emit`` logs nothing of its own so an action
    shows up once rather than twice. A line named after a kind reintroduces the double by hand."""
    said_twice = {name for _, name in _log_sites()} & set(catalog.kinds())

    assert said_twice == set()


def test_no_context_writes_a_line_under_another_apps_name():
    """A name's first segment is a claim of ownership — the same string that keys the app's
    settings, console tile and event kinds. Only that app gets to make it."""
    contexts = _contexts()
    strays = {
        f"{context} writes {name}"
        for context, name in _log_sites()
        if (claimed := name.split(".")[0]) in contexts and claimed != context
    }

    assert strays == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: an AST shape that matched nothing would make both assertions vacuous.
    assert len(_log_sites()) > 50
