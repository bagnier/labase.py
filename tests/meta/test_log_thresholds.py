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
(``log_at = log.error``), so it stays out of this walk by construction rather than by exemption.

Same shape and same reason as its two siblings: these choices live at call sites, so nothing but
an AST walk enumerates them.
"""

import ast
from pathlib import Path

_APPS = Path(__file__).resolve().parents[2] / "apps"


def _calls_at(level: str) -> list[tuple[str, str, ast.Call]]:
    """Every ``(site, name, call)`` spelling ``log.<level>(…)`` under ``apps/``, tests aside."""
    found = []
    for path in sorted(_APPS.rglob("*.py")):
        if "/tests/" in path.as_posix():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == level
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "log"
            ):
                continue
            first = node.args[0] if node.args else None
            name = first.value if isinstance(first, ast.Constant) else "<caller-supplied>"
            found.append((f"{path.relative_to(_APPS.parent)}:{node.lineno}", str(name), node))
    return found


def test_an_error_line_carries_the_exception_that_justifies_it():
    """Without one it alarms nobody: the seam skips it, and the line rolls out of its window."""
    blind = {
        f"{name} ({site})"
        for site, name, call in _calls_at("error")
        if not any(keyword.arg == "exc_info" for keyword in call.keywords)
    }

    assert blind == set()


def test_the_walk_actually_finds_the_error_sites():
    # Guards the guard: an AST shape that matched nothing would make the assertion vacuous.
    assert len(_calls_at("error")) > 0


# Every ``info`` the base admits, and nothing else. The list is the point: an ``info`` reports a
# point of surprise, and a codebase holds only so many genuine surprises before the level stops
# meaning anything. Adding one is a deliberate edit, argued here, rather than something that
# happens while writing a handler.
#
# Two more are written through a bound alias and so fall outside this walk, both for the same
# reason — their *level* is computed from an outcome: ``request.finished`` (``log_at``), which is
# ``info`` only when the exchange did what was asked, and ``LoopHealth``'s ``…_recovered``
# (``self._log``), which says what an outage cost once it is over.
_THE_SURPRISES = {
    # A reaction whose actor closed their account between the fact and its delivery — the
    # personal org, the first-admin grant. Rare, and it explains a missing row later.
    "bootstrap_first_admin.actor_gone (apps/console/contract/integration.py)",
    "create_personal_org.actor_gone (apps/organizations/contract/integration.py)",
    "seed_org_welcome.actor_gone (apps/organizations/contract/queries.py)",
    # An admin-role write the server took whose echoed record the SDK could not parse (an
    # anonymized identity): the action landed, and this explains the missing confirmation.
    "set_server_admin.record_unreadable (apps/auth/infra/user_repository.py)",
    # A dependency that answered *no*: the ordinary half of the verdict, whose other half is an
    # issue. The name comes from the caller, so the walk cannot read it off the constant.
    "<caller-supplied> (apps/shared/logs/dependency.py)",
    # The log store taking lines again, carrying what the outage cost.
    "log_sink.write_recovered (apps/shared/logs/sink.py)",
    # A request whose SQL crossed a threshold, naming the statements that cost the time.
    "db.heavy_request (apps/shared/persistence/sql_stats.py)",
}


def test_the_info_lines_are_exactly_the_surprises():
    """A healthy server at rest writes nothing; every name below is a thing that did not go as a
    reader would have predicted."""
    written = {f"{name} ({site.split(':')[0]})" for site, name, _ in _calls_at("info")}

    assert written == _THE_SURPRISES


def test_nothing_is_written_below_the_two_levels():
    """``debug`` answers "what did it do", which the exchange line and the journal answer between
    them — and it charges a line per statement, on every request, to do it. The one thing it
    uniquely bought is ``db.heavy_request``: the same drill-down, written only when there is
    something to drill into."""
    below = [f"{name} ({site})" for site, name, _ in _calls_at("debug")]

    assert below == []
