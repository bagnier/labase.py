"""The ``log_lines`` retention floor is computed once, in ``roll_log_partitions``: no Python in
the repository builds one from ``retention_days``, which a later edit could make disagree.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY = _ROOT / "apps/shared/logs/repository.py"


def _builds_a_floor(call: ast.Call) -> bool:
    """A ``timedelta`` built from ``retention_days``, in any unit or with any offset."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "timedelta"):
        return False
    arguments = list(call.args) + [keyword.value for keyword in call.keywords]
    return any(
        isinstance(name, ast.Name) and name.id == "retention_days"
        for argument in arguments
        for name in ast.walk(argument)
    )


def _is_floor(node: ast.BinOp) -> bool:
    """``<date> - <retention_days timedelta>``."""
    return any(
        isinstance(call, ast.Call) and _builds_a_floor(call) for call in ast.walk(node.right)
    )


def _floors_recomputed_from_retention_days(tree: ast.Module) -> list[int]:
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and _is_floor(node)
    ]


def test_the_retention_floor_is_not_recomputed_in_python():
    tree = ast.parse(_REPOSITORY.read_text())
    assert _floors_recomputed_from_retention_days(tree) == []


def test_the_scan_flags_a_floor_with_a_grace_day():
    """Guards the guard: the detector catches a grace day."""
    snippet = (
        "def purge(retention_days):\n    floor = now.date() - timedelta(days=retention_days + 1)\n"
    )
    assert _floors_recomputed_from_retention_days(ast.parse(snippet)) == [2]


def test_the_scan_flags_a_floor_with_a_changed_unit():
    snippet = "def purge(retention_days):\n    floor = now - timedelta(hours=retention_days)\n"
    assert _floors_recomputed_from_retention_days(ast.parse(snippet)) == [2]
