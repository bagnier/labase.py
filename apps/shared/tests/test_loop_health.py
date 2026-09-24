"""One verdict for a background loop whose tick failed: a blip, or the machinery is down.

The five lifespan workers all caught everything and warned — so a listener or a task worker
that stopped delivering left nothing in the console at all, only warnings inside a log
window that rolls over in two days. The other half of the problem is why they warned: these
loops tick once a second, so promoting every failed tick to ``log.exception`` would open the
same issue eighty-six thousand times a day.

Hence a verdict rather than a level: the *transition* into failure is the bug (one issue, one
occurrence), the ticks that follow are the same outage still running (a warning carrying how
long), and coming back says what it cost. The transition is tracked per *fault*, not per
outage: a second, distinct exception arriving mid-outage is its own bug and opens its own
issue, however many ticks a fault already seen this outage go on warning.
"""

from collections.abc import Callable

import structlog

from apps.shared.logs import capture
from apps.shared.logs.loop import LoopHealth

_PROBE_LOGGER = "apps.todo.infra.router"


def _health() -> LoopHealth:
    capture._QUEUE.clear()
    return LoopHealth(structlog.get_logger(_PROBE_LOGGER), "probe.tick")


def _captured() -> list[tuple[str, str]]:
    return [(str(c.context.get("event")), str(c.exc)) for c in capture._QUEUE]


def _lines(log_chain) -> list[tuple[str, str, dict]]:
    """The probe's own lines, oldest first — the store reads newest first, and what these
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
    """One fault is one issue. Ticking at a second, the alternative is eighty-six thousand
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


def test_a_second_distinct_failure_during_the_outage_opens_its_own_issue(log_chain):
    """A `TypeError` arriving mid-outage is not the same bug as the `RuntimeError` that opened
    it — folding it into the same warning is how it never reaches the issues screen at all."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))

    assert _captured() == [
        ("probe.tick_failed", "still down"),
        ("probe.tick_failed", "a different fault altogether"),
    ]


def test_two_faults_taking_turns_each_open_only_once(log_chain):
    """The transition tracks *which* faults already opened this outage, not merely the last
    one seen — otherwise two faults alternating tick to tick would reopen the issue every time,
    which is the same flood this module exists to avoid, just spread over two exception types."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))
    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))

    assert len(_captured()) == 2


def _raise_from_site_a() -> None:
    raise RuntimeError("still down")


def _raise_from_site_b() -> None:
    raise RuntimeError("still down")


def _raised_by(raiser: Callable[[], None]) -> RuntimeError:
    try:
        raiser()
    except RuntimeError as exc:
        return exc
    raise AssertionError("the probe raiser did not raise")


def test_the_same_exception_type_from_a_different_call_site_is_a_distinct_fault(log_chain):
    """A `RuntimeError` from the claim query and a `RuntimeError` from the commit that follows
    it are two different bugs sharing a type — the fingerprint is the raise site, not the type
    alone, or the second one folds into the first's warnings same as issue #55's original bug."""
    health = _health()

    health.tick_failed(_raised_by(_raise_from_site_a))
    health.tick_failed(_raised_by(_raise_from_site_b))

    assert len(_captured()) == 2


def test_a_fault_reopening_mid_outage_still_says_how_long_it_has_run(log_chain):
    """The opening line for the very first failure carries no count (there is nothing to say
    yet), but one that opens after the outage has already run for a while is not that case —
    losing the count there reads as a fresh outage instead of one 3 ticks deep."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))

    assert _lines(log_chain)[-1] == ("error", "probe.tick_failed", {"failures": 3})


def test_a_loop_coming_back_says_what_the_outage_cost(log_chain):
    """The toll is only final once a tick succeeds, so the recovery line is the one that carries
    it — the same reason the log sink reports its own write outage on the way out."""
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
