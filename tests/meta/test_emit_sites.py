"""No fact leaves its transaction: ``emit`` is the only way in, and nothing emits after a commit
(AGENTS: `emit` records a fact and does only that).
"""

import ast
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"


def _emit_variants() -> set[str]:
    return {
        node.func.attr
        for path in _APPS.rglob("*.py")
        if "/tests/" not in path.as_posix()
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr.startswith("emit")
    }


def _functions(tree: ast.Module):
    yield (
        "<module>",
        [
            node
            for node in tree.body
            if not isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
        ],
    )

    def visit(node: ast.AST, prefix: str):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    yield name, child.body
                yield from visit(child, f"{name}.")

    yield from visit(tree, "")


def _own_nodes(body: list[ast.stmt]):
    """A def's body nodes, nested defs aside."""
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        yield node
        stack.extend(
            child
            for child in ast.iter_child_nodes(node)
            if not isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        )


def _writer_callers() -> dict[str, set[str]]:
    """Callers of each link of the write chain (SQL function, statement, helper, repository
    method), by function."""
    callers: dict[str, set[str]] = defaultdict(set)
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        relative = str(path.relative_to(_ROOT))
        for name, body in _functions(ast.parse(path.read_text())):
            nodes = list(_own_nodes(body))
            site = f"{relative}::{name}"
            names_the_repository = any(
                isinstance(node, ast.Name) and node.id == "EventRepository" for node in nodes
            )
            for node in nodes:
                if (
                    isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and "record_business_event(" in node.value
                ):
                    callers["record_business_event"].add(site)
                elif isinstance(node, ast.Name) and node.id in {"_RECORD", "_append_record"}:
                    if isinstance(node.ctx, ast.Load):
                        callers[node.id].add(site)
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "record"
                    and names_the_repository
                ):
                    callers["EventRepository.record"].add(site)
    return dict(callers)


def _touches(stmt: ast.stmt, attr: str) -> bool:
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attr
        for node in _own_nodes([stmt])
    )


def _commit_before_emit_sites() -> set[str]:
    """Routes where ``.commit()`` precedes ``.emit(``."""
    sites: set[str] = set()
    for path in sorted(_APPS.rglob("infra/router.py")):
        relative = str(path.relative_to(_ROOT))
        for name, body in _functions(ast.parse(path.read_text())):
            seen_commit = False
            for stmt in body:
                if seen_commit and _touches(stmt, "emit"):
                    sites.add(f"{relative}::{name}")
                if _touches(stmt, "commit"):
                    seen_commit = True
    return sites


def test_the_only_way_to_record_a_fact_is_on_a_transaction():
    assert _emit_variants() == {"emit"}


def test_no_route_commits_before_emitting_its_fact():
    """After the commit, a raise in between would keep the row and lose the fact."""
    assert _commit_before_emit_sites() == set()


def test_every_link_of_the_journal_writer_has_its_one_caller():
    """Each link of the chain has one caller, the next one up: ``emit`` is the only door."""
    events = "apps/shared/events"

    assert _writer_callers() == {
        "record_business_event": {f"{events}/repository.py::<module>"},
        "_RECORD": {f"{events}/repository.py::_append_record"},
        "_append_record": {f"{events}/repository.py::EventRepository.record"},
        "EventRepository.record": {f"{events}/bus.py::EventBus.emit"},
    }
