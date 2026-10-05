"""``LoopHealth``: a fault's first failing tick opens an issue, the next ones warn with a count,
recovery says what the outage cost (AGENTS: a failure that repeats is one bug)."""

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
    """The probe's lines oldest first, without the traceback."""
    return [
        (line.level, line.name, {k: v for k, v in line.payload.items() if k != "exception"})
        for line in reversed(log_chain())
        if line.logger == _PROBE_LOGGER
    ]


def test_a_loop_falling_over_opens_an_issue(log_chain):
    health = _health()

    health.tick_failed(RuntimeError("the claim query blew up"))

    assert _captured() == [("probe.tick_failed", "the claim query blew up")]


def test_a_loop_still_down_does_not_open_the_issue_again(log_chain):
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))

    assert len(_captured()) == 1


def test_a_loop_still_down_keeps_saying_so(log_chain):
    """Else an outage still running reads like one that is over."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))

    assert _lines(log_chain) == [
        ("error", "probe.tick_failed", {}),
        ("warning", "probe.tick_failed", {"failures": 2}),
    ]


def test_a_second_distinct_failure_during_the_outage_opens_its_own_issue(log_chain):
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))

    assert _captured() == [
        ("probe.tick_failed", "still down"),
        ("probe.tick_failed", "a different fault altogether"),
    ]


def test_two_faults_taking_turns_each_open_only_once(log_chain):
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
    health = _health()

    health.tick_failed(_raised_by(_raise_from_site_a))
    health.tick_failed(_raised_by(_raise_from_site_b))

    assert len(_captured()) == 2


def test_a_fault_reopening_mid_outage_still_says_how_long_it_has_run(log_chain):
    """Only the outage's very first line has no count."""
    health = _health()

    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(RuntimeError("still down"))
    health.tick_failed(TypeError("a different fault altogether"))

    assert _lines(log_chain)[-1] == ("error", "probe.tick_failed", {"failures": 3})


def test_a_loop_coming_back_says_what_the_outage_cost(log_chain):
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
    health = _health()

    health.tick_succeeded()
    health.tick_succeeded()

    assert _lines(log_chain) == []
