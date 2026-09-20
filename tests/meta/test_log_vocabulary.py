"""One invariant over the *log line names*: a line never spells a fact, nor claims another app.

``tests/meta/test_event_vocabulary`` pins what the journal says. This pins what the log sink says,
and the rule holding the two apart — because they meet again in the console's Timeline, where a
reader tells a fact from a trace by its **source**, never by re-reading its name. A line spelling
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
import re
from pathlib import Path

import apps.main  # noqa: F401  — mounting every app fills the catalog
from apps.shared.events.catalog import catalog

_APPS = Path(__file__).resolve().parents[2] / "apps"
_LEVELS = {"debug", "info", "warning", "error", "exception"}
# What a logger is called at a call site: the module's ``log``, a ``logger``, a ``_log`` field.
_A_LOGGER = re.compile(r"(self\.)?_?log(ger)?")

# The journal's write path — where a fact is recorded, and the one place "emit logs nothing of
# its own" is decided.
_WRITE_PATH = ("shared/events/bus.py", "shared/events/repository.py")

# What the write path does say: two degradations — a pin the writer could not take, a secret it
# had to mask — each at the level it earns. Neither restates the action; a third line here is a
# fact said twice.
_THE_WRITE_PATH_SAYS = {"business_event.names_unpinned", "business_event.secret_field_masked"}


def is_a_logger(receiver: ast.expr) -> bool:
    """Whether ``receiver.<level>(…)`` is a log line — by what the receiver is called, since a
    logger arrives as a module global, a parameter or a field, never under one spelling."""
    return _A_LOGGER.fullmatch(ast.unparse(receiver)) is not None


def _log_sites() -> set[tuple[str, str, str]]:
    """Every ``(context, name, file)`` a ``<logger>.<level>("name", …)`` call declares under
    ``apps/``, tests aside — the context being the package the file lives in (``shared`` for the
    base itself)."""
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
    """A fact is recorded once, on the journal, and ``emit`` logs nothing of its own so an action
    shows up once rather than twice. A line named after a kind reintroduces the double by hand."""
    said_twice = {name for _, name, _ in _log_sites()} & set(catalog.kinds())

    assert said_twice == set()


def test_the_emit_path_says_nothing_of_its_own():
    """ "`emit` logs nothing of its own, so an action shows up once, not twice" — the sibling
    above forbids a line *named* like a fact; this forbids a line on the write path at all, but
    for the two degradations frozen in `_THE_WRITE_PATH_SAYS`, which say what the writer could
    not do rather than what the action did."""
    said = {name for _, name, file in _log_sites() if file in _WRITE_PATH}

    assert said == _THE_WRITE_PATH_SAYS


def test_no_context_writes_a_line_under_another_apps_name():
    """A name's first segment is a claim of ownership — the same string that keys the app's
    settings, console tile and event kinds. Only that app gets to make it."""
    contexts = _contexts()
    strays = {
        f"{context} writes {name}"
        for context, name, _ in _log_sites()
        if (claimed := name.split(".")[0]) in contexts and claimed != context
    }

    assert strays == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: an AST shape that matched nothing would make both assertions vacuous.
    assert len(_log_sites()) > 50
