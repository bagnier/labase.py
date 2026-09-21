"""Two invariants over the *handlers*: a broad ``except`` speaks, and carries its traceback.

``tests/meta/test_log_vocabulary`` pins what a line is *called*; this pins what it is allowed to
leave out. ``except Exception`` is the base's way of saying "whatever went wrong here must not
take the caller down" — and precisely because it names nothing, the exception itself is the only
thing that says what did go wrong. A line that drops it leaves an event name and no message, no
type and no stack: enough to know something failed, never enough to know what.

The doctrine it enforces is the one written in ``apps/shared/logs/capture``:

- ``log.exception`` — a bug; the capture seam folds it into an issue (``exc_info`` implicit).
- ``log.warning(..., exc_info=exc)`` — degraded but handled; the stack reaches the log sink and
  **no** issue opens, since the seam only fires on ``error`` level.

The third rule is the floor under those two: a broad handler that says *nothing* — no line, no
re-raise, no exception handed on — loses the failure outright, and its ``return None`` is
indistinguishable from a legitimate empty answer. Narrowing the clause is the way out as often as
logging is: a decode that can only fail as a ``ValueError`` says so in its ``except``.

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

_APPS = Path(__file__).resolve().parents[2] / "apps"
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


def _carries_a_traceback(keyword: ast.keyword) -> bool:
    """``exc_info=`` with something live behind it. ``exc_info=None`` or ``False`` is the keyword
    present and the traceback gone — structlog then writes no ``exception`` key at all."""
    if keyword.arg != "exc_info":
        return False
    return not (isinstance(keyword.value, ast.Constant) and not keyword.value.value)


def _logging_helpers() -> dict[str, bool]:
    """Each function under ``apps/`` that is handed an exception and logs it — directly or through
    another such helper — with whether *every* line it can write carries the traceback. A broad
    handler calling one says what the helper says, so it is judged by the helper's lines."""
    bodies: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for path in _APPS.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and any(
                arg.arg in {"exc", "error", "e"} for arg in node.args.args + node.args.kwonlyargs
            ):
                bodies[node.name] = node
    carries: dict[str, bool] = {}
    changed = True
    while changed:
        changed = False
        for name, fn in bodies.items():
            direct = [
                any(map(_carries_a_traceback, call.keywords))
                for call in _log_calls(fn)
                if call.func.attr in _MUST_CARRY  # type: ignore[union-attr]
            ]
            through = [carries[callee] for callee in _helper_calls(fn, carries)]
            if (direct or through) and carries.get(name) != all(direct + through):
                carries[name] = all(direct + through)
                changed = True
    return carries


def _helper_calls(node: ast.AST, helpers: dict[str, bool]) -> list[str]:
    """The helpers ``node`` calls, by name — ``helper(...)`` or ``module.helper(...)``."""
    return [
        name
        for child in ast.walk(node)
        if isinstance(child, ast.Call)
        and (
            name := child.func.id
            if isinstance(child.func, ast.Name)
            else child.func.attr
            if isinstance(child.func, ast.Attribute)
            else ""
        )
        in helpers
    ]


def _broad_handler_logs() -> list[tuple[str, str, bool]]:
    """Every ``(site, event name, carries the traceback)`` logged from a broad ``except`` — by a
    ``log.*`` call in the handler, or by a logging helper it hands the exception to."""
    helpers = _logging_helpers()
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
                found.append((site, str(name), any(map(_carries_a_traceback, call.keywords))))
            for helper in _helper_calls(node, helpers):
                site = f"{path.relative_to(_APPS.parent)}:{node.lineno}"
                found.append((site, f"via {helper}", helpers[helper]))
    return found


def test_a_broad_except_never_logs_without_its_traceback():
    """An `except Exception` that logs a bare name loses the only description of what happened."""
    mute = {f"{name} ({site})" for site, name, carries in _broad_handler_logs() if not carries}

    assert mute == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: an AST shape that matched nothing would make the assertion vacuous.
    assert len(_broad_handler_logs()) > 10


# The one broad handler allowed to let its exception go, and the reason it must: it *is* the log
# drain's own write. Anything said inside it — a line, a verdict — is enqueued into the very queue
# the drain has just failed to empty, so the outage is announced outside the handler instead
# (``report_write_outage``, once per transition). Same argument, same shape as the two loops
# ``tests/meta/test_loop_verdicts`` excludes by name.
_LETS_IT_GO = ("apps/shared/logs/sink.py", "tick")


def _broad_handlers(node: ast.AST, path: str, function: str):
    """Every broad ``except`` under ``node``, paired with the function that holds it."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _broad_handlers(child, path, child.name)
            continue
        if isinstance(child, ast.ExceptHandler) and _is_broad(child):
            yield path, function, child
        yield from _broad_handlers(child, path, function)


def _keeps_the_exception(handler: ast.ExceptHandler) -> bool:
    """Whether the failure goes anywhere at all: re-raised, logged, or handed on by its name.

    Handing it on covers the two shapes the base already uses — a reporting helper that decides the
    level (``log_dependency_failure``, ``_log_gotrue_failure``), and a verdict deferred to a batch
    (``failures.append(exc)``, ``self._health.tick_failed(exc)``). All three are named in the
    ``except`` clause, so the bound name being *used* is the honest test, and it needs no list of
    blessed helper names to keep up to date.
    """
    if any(isinstance(node, ast.Raise) for node in ast.walk(handler)):
        return True
    if any(_log_calls(handler)):
        return True
    if handler.name is None:
        return False
    return any(isinstance(node, ast.Name) and node.id == handler.name for node in ast.walk(handler))


def _mute_broad_handlers() -> set[str]:
    """Every broad ``except`` where the exception simply vanishes."""
    found = set()
    for path in _APPS.rglob("*.py"):
        if "/tests/" in path.as_posix():
            continue
        relative = str(path.relative_to(_APPS.parent))
        for _, function, handler in _broad_handlers(ast.parse(path.read_text()), relative, ""):
            if (relative, function) == _LETS_IT_GO or _keeps_the_exception(handler):
                continue
            found.add(f"{relative}:{handler.lineno} in {function}()")
    return found


def test_a_broad_except_never_loses_the_exception_entirely():
    """The rule above says a handler that speaks must carry its traceback; this one says it has to
    speak. ``except Exception: return None`` reads like handling and is the opposite: the failure
    leaves no line, no issue and no return value distinguishable from a legitimate empty answer."""
    lost = _mute_broad_handlers()

    assert lost == set()


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
