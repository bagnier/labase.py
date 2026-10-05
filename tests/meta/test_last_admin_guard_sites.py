"""Every ``ensure_not_last_admin`` site holds ``lock_last_admin_guard`` (the mechanism is tested in
``apps/console/tests/test_admins_concurrency.py``): the function itself, or every caller of it,
since the domain function has no session to lock.
"""

import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"

_GUARD_CALL = "ensure_not_last_admin"
_LOCK_CALL = "lock_last_admin_guard"


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _not_a_def(nodes) -> list[ast.AST]:
    _def_types = ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    return [n for n in nodes if not isinstance(n, _def_types)]


def _own_calls(body: list[ast.stmt]):
    """A def's calls, nested defs excluded, including those right in the body."""
    stack: list[ast.AST] = _not_a_def(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            yield node
        stack.extend(_not_a_def(ast.iter_child_nodes(node)))


def _function_defs(tree: ast.Module):
    """Every ``def``, methods included."""

    def visit(node: ast.AST):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield child
            yield from visit(child)

    yield from visit(tree)


@dataclass(frozen=True)
class _Fn:
    qualname: str
    calls: list[tuple[int, str]]  # (lineno, name), own body


def _every_function() -> list[_Fn]:
    found = []
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text())
        for fn in _function_defs(tree):
            calls = [(n.lineno, name) for n in _own_calls(fn.body) if (name := _call_name(n))]
            found.append(_Fn(f"{path.relative_to(_ROOT)}:{fn.name}", calls))
    return found


def _locks_before(calls: list[tuple[int, str]], before_line: int) -> bool:
    return any(name == _LOCK_CALL and lineno <= before_line for lineno, name in calls)


def _unguarded_sites(functions: list[_Fn]) -> list[str]:
    callers_by_name: dict[str, list[_Fn]] = defaultdict(list)
    for fn in functions:
        for _, name in fn.calls:
            callers_by_name[name].append(fn)

    offenders = []
    for fn in functions:
        guard_lines = [lineno for lineno, name in fn.calls if name == _GUARD_CALL]
        if not guard_lines:
            continue
        if _locks_before(fn.calls, guard_lines[0]):
            continue
        short_name = fn.qualname.rsplit(":", 1)[-1]
        callers = callers_by_name.get(short_name, [])
        if callers and all(
            _locks_before(caller.calls, next(ln for ln, name in caller.calls if name == short_name))
            for caller in callers
        ):
            continue
        offenders.append(f"{fn.qualname}:{guard_lines[0]}")
    return offenders


# By name, so a scan finding nothing fails.
_KNOWN_GUARD_SITES = {"set_admin", "account_delete", "_guard_last_admin"}


def test_every_last_admin_guard_check_is_preceded_by_the_lock():
    functions = _every_function()
    found = {
        fn.qualname.rsplit(":", 1)[-1]
        for fn in functions
        if any(n == _GUARD_CALL for _, n in fn.calls)
    }
    assert found == _KNOWN_GUARD_SITES
    assert _unguarded_sites(functions) == []
