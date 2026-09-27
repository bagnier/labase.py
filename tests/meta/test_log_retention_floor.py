"""The retention floor for ``log_lines`` is computed once, in SQL: ``roll_log_partitions`` alone
decides which day is old enough to drop, and the row-level cleanup of what a whole-partition
drop cannot reach reads that same ``floor_day`` rather than a second expression of its own. Two
independent floors (issue #92, following #43) agree only by accident — a grace day, an inclusive
bound, or a change of unit edited into one side alone would silently let the row-level delete
reach into, or stop short of, the partition the roll actually kept, with nothing to notice it.

The scan below holds "the floor day should be computed once and shared, not asserted twice": no
function in the repository module builds a retention floor out of ``retention_days`` — that
arithmetic belongs to ``roll_log_partitions`` alone.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY = _ROOT / "apps/shared/logs/repository.py"


def _builds_a_floor(call: ast.Call) -> bool:
    """Is this a ``timedelta(...)`` built out of ``retention_days`` — in days, another unit, or
    with an offset (a grace day, a changed unit)? Positional or keyword, any arithmetic on it."""
    if not (isinstance(call.func, ast.Name) and call.func.id == "timedelta"):
        return False
    arguments = list(call.args) + [keyword.value for keyword in call.keywords]
    return any(
        isinstance(name, ast.Name) and name.id == "retention_days"
        for argument in arguments
        for name in ast.walk(argument)
    )


def _is_floor(node: ast.BinOp) -> bool:
    """Is this ``<date-expr> - <retention_days-shaped timedelta>`` — the shape that recomputes,
    in Python, the floor ``roll_log_partitions`` already decided in SQL?"""
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
    """Guards the guard: a detector that never matches anything would let the test above pass
    for the wrong reason. A grace day is one of the edits the issue names as a way to reopen
    #43 unnoticed."""
    snippet = (
        "def purge(retention_days):\n    floor = now.date() - timedelta(days=retention_days + 1)\n"
    )
    assert _floors_recomputed_from_retention_days(ast.parse(snippet)) == [2]


def test_the_scan_flags_a_floor_with_a_changed_unit():
    snippet = "def purge(retention_days):\n    floor = now - timedelta(hours=retention_days)\n"
    assert _floors_recomputed_from_retention_days(ast.parse(snippet)) == [2]
