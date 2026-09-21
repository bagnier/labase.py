"""One invariant over the *call sites*: no fact gives up its transaction.

``tests/meta/test_event_vocabulary`` walks the catalog — every event **class**, enumerable because a
class registers itself at import. Nothing enumerated the **emit sites**, and that is where the
divergence lived: two facts about one action, in one handler, could carry different durability
guarantees with nothing saying so.

That is settled twice over. ``emit`` takes its session as a required argument, so the type checker
enumerates the sites; and the escape hatch that briefly existed for the facts a rollback would
erase — the security refusals — is gone, because those turned out to describe nothing that happened
and are log lines now. ``apps/shared/tests/test_emit_durability`` holds the mechanism that made a
raising path the only case ever needing one.

This is the ratchet on that: an escape hatch is easy to reintroduce and much harder to notice.
"""

import ast
from collections import defaultdict
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_APPS = _ROOT / "apps"


def _emit_variants() -> set[str]:
    """Every ``….emit*`` method name called under ``apps/``, tests aside."""
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
    """Each def in a module with its qualified name, and the module body itself as ``<module>``."""
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
    """The nodes of a def's body, not descending into the defs nested in it — those are named on
    their own."""
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
    """Who reaches each link of the journal's write chain — the SQL function's name, the statement
    that calls it, the helper running that statement, and the repository method wrapping the
    helper — named by the function doing it, tests aside."""
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


def test_the_only_way_to_record_a_fact_is_on_a_transaction():
    """A second entry point would have to weaken durability to be worth adding at all."""
    assert _emit_variants() == {"emit"}


def test_every_link_of_the_journal_writer_has_its_one_caller():
    """The name of the method is one entry point; the chain behind it is four more. A route calling
    ``EventRepository(s).record(e)`` or ``_append_record`` directly skips nothing ``emit`` checks
    today, and everything it may check tomorrow — so each link has exactly one caller, the next
    link up, and ``emit`` is the only door."""
    events = "apps/shared/events"

    assert _writer_callers() == {
        "record_business_event": {f"{events}/repository.py::<module>"},
        "_RECORD": {f"{events}/repository.py::_append_record"},
        "_append_record": {f"{events}/repository.py::EventRepository.record"},
        "EventRepository.record": {f"{events}/bus.py::EventBus.emit"},
    }
