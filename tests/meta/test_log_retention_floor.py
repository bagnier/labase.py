"""The retention floor for ``log_lines`` is computed once, in SQL — ``roll_log_partitions`` alone
decides which day is old enough to drop. Before this test, ``LogRepository.purge`` computed the
same floor a second time, in Python, from the same ``retention_days`` — one in
``now.date() - timedelta(days=retention_days)``, the other in
``(p_today - make_interval(days => p_retention_days))::date`` — with nothing binding the two
expressions together (issue #92, following #43). An edit to either side alone (a grace day, an
inclusive bound, a change of unit) would silently let the row-level DELETE reach into, or stop
short of, the partition the roll actually kept, and no test would notice, since the retention
tests exercise each floor through its own language.

The scan below holds "the floor day should be computed once and shared, not asserted twice": no
function in the repository module builds a retention floor by subtracting ``retention_days`` from
a date — that arithmetic belongs to ``roll_log_partitions`` alone.
"""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_REPOSITORY = _ROOT / "apps/shared/logs/repository.py"


def _is_floor(node: ast.BinOp) -> bool:
    """Is this ``<date-expr> - timedelta(days=retention_days)`` — the shape that recomputes, in
    Python, the floor ``roll_log_partitions`` already decided in SQL?"""
    right = node.right
    if not (
        isinstance(right, ast.Call)
        and isinstance(right.func, ast.Name)
        and right.func.id == "timedelta"
    ):
        return False
    return any(
        keyword.arg == "days"
        and isinstance(keyword.value, ast.Name)
        and keyword.value.id == "retention_days"
        for keyword in right.keywords
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


def test_the_scan_flags_a_floor_recomputed_from_retention_days():
    """Guards the guard: a detector that never matches anything would let the test above pass
    for the wrong reason."""
    snippet = (
        "def purge(retention_days):\n    floor = now.date() - timedelta(days=retention_days)\n"
    )
    assert _floors_recomputed_from_retention_days(ast.parse(snippet)) == [2]
