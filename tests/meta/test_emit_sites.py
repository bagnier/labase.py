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
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2] / "apps"


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


def test_the_only_way_to_record_a_fact_is_on_a_transaction():
    """A second entry point would have to weaken durability to be worth adding at all."""
    assert _emit_variants() == {"emit"}
