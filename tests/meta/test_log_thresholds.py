"""One invariant over the *levels*: what the capture seam can see, and what it cannot.

``tests/meta/test_log_vocabulary`` pins what a line is called, ``tests/meta/test_capture_sites``
what a broad ``except`` may leave out. This one pins the doctrine's own arithmetic
(:mod:`apps.shared.logs.capture`): two levels and a seam, and nothing underneath them.

``error`` is the level the seam reads — but only carrying a live exception, since
``capture_processor`` fires on "error level with ``exc_info``" and on nothing else. A bare
``log.error`` is therefore the one spelling that *looks* like an alarm and reaches no console: it
writes a line into a window that rolls over, and opens no issue. The two sites that used to spell
it were both doubles of something already said one line earlier — a preflight error the process
was about to raise anyway, a parked task the seam had just captured.

The one deliberate ``error`` carrying no exception is ``request.finished`` on a 5xx, which states
the *outcome* of an exchange rather than a defect. It is written through a bound alias
(``log_at = log.error if … else log.info``), which the walk resolves to every level it can take —
so it is named below as the one outcome line, rather than left out by the shape of its call.

Same shape and same reason as its two siblings: these choices live at call sites, so nothing but
an AST walk enumerates them.
"""

import ast
from pathlib import Path

from tests.meta.test_log_vocabulary import is_a_logger

_APPS = Path(__file__).resolve().parents[2] / "apps"


def _levels_of(value: ast.expr) -> set[str]:
    """The levels an expression can bind: ``log.error``, or either branch of an ``if``/``else``
    choosing between two — empty for anything that is not a logger's level."""
    if isinstance(value, ast.IfExp):
        return _levels_of(value.body) | _levels_of(value.orelse)
    if isinstance(value, ast.Attribute) and is_a_logger(value.value):
        return {value.attr}
    return set()


def _bound_levels(tree: ast.Module) -> dict[str, set[str]]:
    """Each name bound to a logger's level somewhere in the module, with every level it can take
    — ``log_at = log.error if … else log.info``, then ``log_at = log.warning``."""
    bound: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and (levels := _levels_of(node.value)):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bound.setdefault(target.id, set()).update(levels)
    return bound


def _calls_at(level: str) -> list[tuple[str, str, ast.Call]]:
    """Every ``(site, name, call)`` writing a line at ``level`` under ``apps/``, tests aside —
    ``<logger>.<level>(…)`` whatever the logger is called, and a call through a name bound to a
    level, counted at each level it can take."""
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


# The exchange's own line: its level is computed from the outcome, so it is `error` on a 5xx with
# no exception to carry, and `info` when the exchange did what was asked — neither a defect nor a
# surprise, and the only line allowed to be either.
_THE_OUTCOME_LINE = "request.finished (apps/shared/logs/request.py)"


def test_an_error_line_carries_the_exception_that_justifies_it():
    """Without one it alarms nobody: the seam skips it, and the line rolls out of its window."""
    blind = {
        f"{name} ({site.split(':')[0]})"
        for site, name, call in _calls_at("error")
        if not any(keyword.arg == "exc_info" for keyword in call.keywords)
    }

    assert blind == {_THE_OUTCOME_LINE}


def test_the_walk_actually_finds_the_error_sites():
    # Guards the guard: an AST shape that matched nothing would make the assertion vacuous.
    assert len(_calls_at("error")) > 0


# Every ``info`` the base admits, and nothing else. The list is the point: an ``info`` reports a
# point of surprise, and a codebase holds only so many genuine surprises before the level stops
# meaning anything. Adding one is a deliberate edit, argued here, rather than something that
# happens while writing a handler.
_THE_SURPRISES = {
    # A reaction whose actor closed their account between the fact and its delivery — the
    # personal org, the first-admin grant. Rare, and it explains a missing row later.
    "bootstrap_first_admin.actor_gone (apps/console/contract/integration.py)",
    "create_personal_org.actor_gone (apps/organizations/contract/integration.py)",
    "seed_org_welcome.actor_gone (apps/organizations/contract/queries.py)",
    # The narrower half of that same race: the owner never left, but the org itself was deleted
    # between the pre-check and the seeder's write.
    "seed_org_welcome.org_gone (apps/organizations/contract/queries.py)",
    # An admin-role write the server took whose echoed record the SDK could not parse (an
    # anonymized identity): the action landed, and this explains the missing confirmation.
    "set_server_admin.record_unreadable (apps/auth/infra/user_repository.py)",
    # A dependency that answered *no*: the ordinary half of the verdict, whose other half is an
    # issue. The name comes from the caller, so the walk cannot read it off the constant.
    "<caller-supplied> (apps/shared/logs/dependency.py)",
    # The log store taking lines again, carrying what the outage cost.
    "log_sink.write_recovered (apps/shared/logs/sink.py)",
    # A lifespan loop ticking again after an outage, carrying how many ticks it lost — the name
    # is derived from the loop's, so the walk cannot read it off the constant either.
    "<caller-supplied> (apps/shared/logs/loop.py)",
    # A request whose SQL crossed a threshold, naming the statements that cost the time.
    "db.heavy_request (apps/shared/persistence/sql_stats.py)",
    # A production boot with a non-blocking preflight finding — a configuration observation,
    # not something the code absorbed or refused, but still not the sound-config happy path.
    "preflight.finding (apps/shared/settings/preflight.py)",
}


def test_the_info_lines_are_exactly_the_surprises():
    """A healthy server at rest writes nothing; every name below is a thing that did not go as a
    reader would have predicted."""
    written = {f"{name} ({site.split(':')[0]})" for site, name, _ in _calls_at("info")}

    assert written == _THE_SURPRISES | {_THE_OUTCOME_LINE}


def test_nothing_is_written_below_the_two_levels():
    """``debug`` answers "what did it do", which the exchange line and the journal answer between
    them — and it charges a line per statement, on every request, to do it. The one thing it
    uniquely bought is ``db.heavy_request``: the same drill-down, written only when there is
    something to drill into."""
    below = [f"{name} ({site})" for site, name, _ in _calls_at("debug")]

    assert below == []
