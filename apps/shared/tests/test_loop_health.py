"""One verdict for a background loop whose tick failed: a blip, or the machinery is down.

The five lifespan workers all caught everything and warned — so a listener or a task worker
that stopped delivering left nothing in the console at all, only warnings inside a firehose
window that rolls over in two days. The other half of the problem is why they warned: these
loops tick once a second, so promoting every failed tick to ``log.exception`` would open the
same issue eighty-six thousand times a day.

Hence a verdict rather than a level: the *transition* into failure is the bug (one issue, one
occurrence), the ticks that follow are the same outage still running (a warning carrying how
long), and coming back says what it cost.
"""

import structlog

from apps.shared.observability import capture
from apps.shared.observability.loop import LoopHealth

_PROBE_LOGGER = "apps.todo.infra.router"


def _health() -> LoopHealth:
    capture._QUEUE.clear()
    return LoopHealth(structlog.get_logger(_PROBE_LOGGER), "probe.tick")


def _captured() -> list[tuple[str, str]]:
    return [(str(c.context.get("event")), str(c.exc)) for c in capture._QUEUE]


def _lines(log_chain) -> list[tuple[str, str, dict]]:
    """The probe's own lines, oldest first — the firehose reads newest first, and what these
    tests are about is the *order* an outage is told in. The rendered traceback is dropped: it
    is the exception's text, not this module's verdict."""
    return [
        (line.level, line.name, {k: v for k, v in line.payload.items() if k != "exception"})
        for line in reversed(log_chain())
        if line.logger == _PROBE_LOGGER
    ]


def test_a_loop_falling_over_opens_an_issue(log_chain):
    """A worker that stops delivering is a defect, not a degradation — the console has to say so."""
    health = _health()

    health.tick_failed(RuntimeError("the claim query blew up"))

    assert _captured() == [("probe.tick_failed", "the claim query blew up")]


def test_a_loop_still_down_does_not_open_the_issue_again(log_chain):
    """One outage is one issue. Ticking at a second, the alternative is eighty-six thousand
    occurrences a day for a single failure, which buries every other issue on the screen."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))

    assert len(_captured()) == 1


def test_a_loop_still_down_keeps_saying_so(log_chain):
    """Silence between the transition and the recovery would leave a reader unable to tell an
    outage that is over from one still running. The count is how long it has been running."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))

    assert _lines(log_chain) == [
        ("error", "probe.tick_failed", {}),
        ("warning", "probe.tick_failed", {"failures": 2}),
    ]


def test_a_loop_coming_back_says_what_the_outage_cost(log_chain):
    """The toll is only final once a tick succeeds, so the recovery line is the one that carries
    it — the same reason the firehose reports its own write outage on the way out."""
    health = _health()

    health.tick_failed(RuntimeError("down"))
    health.tick_failed(RuntimeError("down"))
    health.tick_succeeded()

    assert _lines(log_chain) == [
        ("error", "probe.tick_failed", {}),
        ("warning", "probe.tick_failed", {"failures": 2}),
        ("info", "probe.tick_recovered", {"failures": 2}),
    ]


def test_a_healthy_loop_says_nothing(log_chain):
    """A tick that succeeds after a tick that succeeded is the normal case, and the normal case
    is not a log line — otherwise every worker writes one a second, forever."""
    health = _health()

    health.tick_succeeded()
    health.tick_succeeded()

    assert _lines(log_chain) == []
