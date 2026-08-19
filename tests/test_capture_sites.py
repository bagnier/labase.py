"""One invariant over the *handlers*: a broad ``except`` never swallows its traceback.

``tests/test_log_vocabulary`` pins what a line is *called*; this pins what it is allowed to leave
out. ``except Exception`` is the base's way of saying "whatever went wrong here must not take the
caller down" — and precisely because it names nothing, the exception itself is the only thing that
says what did go wrong. A line that drops it leaves an event name and no message, no type and no
stack: enough to know something failed, never enough to know what.

The doctrine it enforces is the one written in ``apps/shared/observability/capture``:

- ``log.exception`` — a bug; the capture seam folds it into an issue (``exc_info`` implicit).
- ``log.warning(..., exc_info=exc)`` — degraded but handled; the stack reaches the firehose and
  **no** issue opens, since the seam only fires on ``error`` level.

A *narrow* ``except`` is out of scope by construction: ``except TotpError`` is a wrong code, a
refusal the code already named, and its traceback is noise.

The second rule here guards the near miss that the first one invites. Reaching for ``exc_info``
and writing ``log.exception("auth.login_error", exc)`` looks right and silently is not: structlog
hands positional arguments to its ``%``-formatter, so the exception is consumed as a format
argument and the traceback is dropped — the very thing the rule above exists to keep. No line in
the base uses ``%``-formatting, so "the event name is the only positional" costs nothing and
makes that spelling impossible.

Same shape and same reason as ``test_log_vocabulary`` and ``test_emit_sites``: these choices live
at call sites, so nothing but an AST walk enumerates them.
"""

import ast
from pathlib import Path

_APPS = Path(__file__).resolve().parent.parent / "apps"
# ``log.exception`` sets ``exc_info=True`` itself, so only the levels that must ask carry the rule.
_MUST_CARRY = {"debug", "info", "warning", "error"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """A handler that names nothing (``except:``) or names the top of the hierarchy."""
    if handler.type is None:
        return True
    return isinstance(handler.type, ast.Name) and handler.type.id in {"Exception", "BaseException"}


def _log_calls(node: ast.AST):
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "log"
        ):
            yield child


def _broad_handler_logs() -> list[tuple[str, str, bool]]:
    """Every ``(site, event name, carries the traceback)`` logged from a broad ``except``."""
    found = []
    for path in _APPS.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.ExceptHandler) and _is_broad(node)):
                continue
            for call in _log_calls(node):
                if call.func.attr not in _MUST_CARRY:  # type: ignore[union-attr]
                    continue
                name = (
                    call.args[0].value
                    if call.args and isinstance(call.args[0], ast.Constant)
                    else "?"
                )
                site = f"{path.relative_to(_APPS.parent)}:{call.lineno}"
                found.append((site, str(name), any(k.arg == "exc_info" for k in call.keywords)))
    return found


def test_a_broad_except_never_logs_without_its_traceback():
    """An `except Exception` that logs a bare name loses the only description of what happened."""
    mute = {f"{name} ({site})" for site, name, carries in _broad_handler_logs() if not carries}

    assert mute == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: an AST shape that matched nothing would make the assertion vacuous.
    assert len(_broad_handler_logs()) > 10


def _positional_log_calls() -> list[str]:
    """Every ``log.<level>(...)`` under ``apps/`` passing more than the event name positionally."""
    return [
        f"{path.relative_to(_APPS.parent)}:{call.lineno}"
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for call in _log_calls(ast.parse(path.read_text()))
        if len(call.args) > 1
    ]


def test_a_log_line_passes_nothing_but_its_name_positionally():
    """``log.exception("x", exc)`` reads as "log this exception" and does the opposite."""
    assert _positional_log_calls() == []
