"""A broad ``except`` (AGENTS: nothing escapes the log chain): it logs with its traceback, or
re-raises, or hands the exception on; never drops it. A narrow one names its refusal already.

The event name is the only positional argument: structlog would consume ``log.exception("x",
exc)``'s exception as a ``%``-format argument and drop the traceback.
"""

import ast
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2] / "apps"
# ``log.exception`` sets ``exc_info`` itself.
_MUST_CARRY = {"debug", "info", "warning", "error"}


def _is_broad(handler: ast.ExceptHandler) -> bool:
    """``except:`` or the top of the hierarchy."""
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
    """A live ``exc_info=``; ``None`` or ``False`` drops the traceback."""
    if keyword.arg != "exc_info":
        return False
    return not (isinstance(keyword.value, ast.Constant) and not keyword.value.value)


def _logging_helpers() -> dict[str, bool]:
    """Helpers under ``apps/`` logging an exception they are handed, with whether all their lines
    carry the traceback; a handler calling one is judged by it."""
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
    """``(site, event, carries the traceback)`` for each line a broad ``except`` writes, itself or
    through a helper."""
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
    mute = {f"{name} ({site})" for site, name, carries in _broad_handler_logs() if not carries}

    assert mute == set()


def test_the_walk_actually_finds_the_call_sites():
    # Guards the guard: a walk matching nothing would make it vacuous.
    assert len(_broad_handler_logs()) > 10


# The log drain's write may drop its exception: a line would feed the queue it failed to empty.
# ``report_write_outage`` says it instead.
_LETS_IT_GO = ("apps/shared/logs/sink.py", "tick")


def _broad_handlers(node: ast.AST, path: str, function: str):
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
            yield from _broad_handlers(child, path, child.name)
            continue
        if isinstance(child, ast.ExceptHandler) and _is_broad(child):
            yield path, function, child
        yield from _broad_handlers(child, path, function)


def _keeps_the_exception(handler: ast.ExceptHandler) -> bool:
    """Re-raised, logged, or its bound name used (``log_dependency_failure(…, exc)``,
    ``failures.append(exc)``): no list of helpers to maintain."""
    if any(isinstance(node, ast.Raise) for node in ast.walk(handler)):
        return True
    if any(_log_calls(handler)):
        return True
    if handler.name is None:
        return False
    return any(isinstance(node, ast.Name) and node.id == handler.name for node in ast.walk(handler))


def _mute_broad_handlers() -> set[str]:
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
    """``except Exception: return None`` loses the failure; narrow the clause or speak."""
    lost = _mute_broad_handlers()

    assert lost == set()


def _positional_log_calls() -> list[str]:
    return [
        f"{path.relative_to(_APPS.parent)}:{call.lineno}"
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for call in _log_calls(ast.parse(path.read_text()))
        if len(call.args) > 1
    ]


def test_a_log_line_passes_nothing_but_its_name_positionally():
    assert _positional_log_calls() == []
