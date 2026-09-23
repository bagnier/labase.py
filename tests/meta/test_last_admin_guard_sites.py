"""One invariant over the *call sites*: whoever checks the last-admin guard holds its lock.

``ensure_not_last_admin`` reads a count an earlier statement fetched; without
``lock_last_admin_guard`` serializing the read against every other caller, two concurrent
callers can both fetch the same stale count and both pass (issue #36). The mechanism is proven
once, generically, by ``apps/console/tests/test_admins_concurrency.py`` — this is the ratchet
that every *site* actually uses it: a route that gains a new ``ensure_not_last_admin`` call
without the lock silently reopens the race the mechanism closes.

The guard's own domain function (framework-free, no session) cannot hold the lock itself — the
router that carries the session does, before calling in. So the check climbs one level: a
function holding the guard call is compliant if it takes the lock itself, or if *every* function
that calls it (by name, own body, apps/ non-test code) takes the lock first.
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
    """The ``ast.Call`` nodes of a def's body, not descending into the defs nested in it —
    those are their own function, and answer for their own calls. Filtered on the way onto the
    stack, not just on the way further down it, or a nested def sitting directly in the body
    (never itself pushed through the filtered branch below) would still be walked."""
    stack: list[ast.AST] = _not_a_def(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Call):
            yield node
        stack.extend(_not_a_def(ast.iter_child_nodes(node)))


def _function_defs(tree: ast.Module):
    """Every ``def``, including methods — a class body is walked too, just never yielded
    itself."""

    def visit(node: ast.AST):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                yield child
            yield from visit(child)

    yield from visit(tree)


@dataclass(frozen=True)
class _Fn:
    qualname: str
    calls: list[tuple[int, str]]  # (lineno, called name), own body only


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


# Every function that currently calls ``ensure_not_last_admin`` — pinned by name, not just by
# count, so the scan finding zero sites (an empty ``apps/`` tree, a renamed root) fails loudly
# instead of reading as "nothing to report".
_KNOWN_GUARD_SITES = {"set_admin", "account_delete", "delete_user"}


def test_every_last_admin_guard_check_is_preceded_by_the_lock():
    functions = _every_function()
    found = {
        fn.qualname.rsplit(":", 1)[-1]
        for fn in functions
        if any(n == _GUARD_CALL for _, n in fn.calls)
    }
    assert found == _KNOWN_GUARD_SITES
    assert _unguarded_sites(functions) == []
