"""Log levels (AGENTS: a line says what no other record says): ``error`` always carries an
exception, the capture seam's only trigger, save ``request.finished`` on a 5xx; ``info`` is a
listed set of surprises; no ``debug``.
"""

import ast
from pathlib import Path

from tests.meta.test_log_vocabulary import is_a_logger

_APPS = Path(__file__).resolve().parents[2] / "apps"


def _levels_of(value: ast.expr) -> set[str]:
    """Levels an expression binds: ``log.error``, or both branches of a conditional."""
    if isinstance(value, ast.IfExp):
        return _levels_of(value.body) | _levels_of(value.orelse)
    if isinstance(value, ast.Attribute) and is_a_logger(value.value):
        return {value.attr}
    return set()


def _bound_levels(tree: ast.Module) -> dict[str, set[str]]:
    """Names bound to a level in the module, with every level each can take."""
    bound: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and (levels := _levels_of(node.value)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, set()).update(levels)
    return bound


def _calls_at(level: str) -> list[tuple[str, str, ast.Call]]:
    """``(site, name, call)`` writing at ``level`` under ``apps/``, aliases included."""
    found = []
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        tree = ast.parse(path.read_text())
        aliases = {name for name, levels in _bound_levels(tree).items() if level in levels}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            direct = (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == level
                and is_a_logger(node.func.value)
            )
            through_alias = isinstance(node.func, ast.Name) and node.func.id in aliases
            if not (direct or through_alias):
                continue
            first = node.args[0] if node.args else None
            name = first.value if isinstance(first, ast.Constant) else "<caller-supplied>"
            found.append((f"{path.relative_to(_APPS.parent)}:{node.lineno}", str(name), node))
    return found


# Its level is the exchange's outcome.
_THE_OUTCOME_LINE = "request.finished (apps/shared/logs/request.py)"


def test_an_error_line_carries_the_exception_that_justifies_it():
    blind = {
        f"{name} ({site.split(':')[0]})"
        for site, name, call in _calls_at("error")
        if not any(keyword.arg == "exc_info" for keyword in call.keywords)
    }

    assert blind == {_THE_OUTCOME_LINE}


def test_the_walk_actually_finds_the_error_sites():
    # Guards the guard: a walk matching nothing would make it vacuous.
    assert len(_calls_at("error")) > 0


# Every ``info`` allowed, each a surprise argued here.
_THE_SURPRISES = {
    # A reaction whose user left before delivery: explains a missing row.
    "bootstrap_first_admin.actor_gone (apps/console/contract/integration.py)",
    "create_personal_org.actor_gone (apps/organizations/contract/integration.py)",
    "seed_org_welcome.actor_gone (apps/organizations/contract/queries.py)",
    # The org deleted between the seeder's check and its write.
    "seed_org_welcome.org_gone (apps/organizations/contract/queries.py)",
    # A role write that landed, its echo unreadable.
    "set_server_admin.record_unreadable (apps/auth/infra/user_repository.py)",
    # A dependency's refusal; the caller names it.
    "<caller-supplied> (apps/shared/logs/dependency.py)",
    # The log store back, with the outage's toll.
    "log_sink.write_recovered (apps/shared/logs/sink.py)",
    # A loop back after an outage; the name is derived.
    "<caller-supplied> (apps/shared/logs/loop.py)",
    "db.heavy_request (apps/shared/persistence/sql_stats.py)",
    # A tracker back after failures.
    "capture.tracker_recovered (apps/shared/logs/capture.py)",
    # A non-blocking preflight finding at a production boot.
    "preflight.finding (apps/shared/settings/preflight.py)",
}


def test_the_info_lines_are_exactly_the_surprises():
    """A healthy server at rest writes nothing."""
    written = {f"{name} ({site.split(':')[0]})" for site, name, _ in _calls_at("info")}

    assert written == _THE_SURPRISES | {_THE_OUTCOME_LINE}


def test_nothing_is_written_below_the_two_levels():
    """``db.heavy_request`` gives the drill-down a per-statement ``debug`` would."""
    below = [f"{name} ({site})" for site, name, _ in _calls_at("debug")]

    assert below == []
