"""The log chain: our lines and the libraries' reach the sink, and so do exceptions no ``except``
saw (AGENTS: nothing escapes the log chain)."""

import asyncio
import json
import logging
import sys
import threading
import warnings

import pytest
import structlog

from apps.shared.logs.chain import catch_loop_exceptions
from apps.shared.logs.sink import fallback_dir


def test_a_line_carries_the_name_of_the_logger_that_wrote_it(log_chain):
    structlog.get_logger("apps.auth.infra.router").warning("auth.login_failed", ip="10.0.0.1")
    lines = log_chain()
    assert [(line.logger, line.name, line.level) for line in lines] == [
        ("apps.auth.infra.router", "auth.login_failed", "warning")
    ]


def test_a_library_log_reaches_the_sink(log_chain):
    logging.getLogger("httpx").warning("connection pool exhausted")
    lines = log_chain()
    assert [(line.logger, line.name, line.level) for line in lines] == [
        ("httpx", "connection pool exhausted", "warning")
    ]


def test_only_a_library_line_is_held_to_the_warning_floor(log_chain):
    logging.getLogger("httpx").info("connection pool refreshed")
    structlog.get_logger("apps.todo.infra.router").info("todo.created")
    lines = log_chain()
    assert [line.logger for line in lines] == ["apps.todo.infra.router"]


def _raise_in_place() -> None:
    raise ValueError("nobody is awaiting me")


def test_an_exception_escaping_a_thread_reaches_the_sink(log_chain):
    thread = threading.Thread(target=_raise_in_place, name="worker-7")
    thread.start()
    thread.join()
    lines = log_chain()
    assert [(line.logger, line.name, line.level) for line in lines] == [
        ("apps.shared.logs.chain", "process.thread_crashed", "error")
    ]


def test_a_crash_on_the_way_out_is_on_disk_before_the_process_dies(log_chain):
    """No loop is left to reach the store: the day file is the only sink."""
    sys.excepthook(ValueError, ValueError("the process gives up"), None)

    written = [
        json.loads(raw)
        for path in fallback_dir().glob("firehose-*.jsonl")
        for raw in path.read_text(encoding="utf-8").splitlines()
    ]

    assert [(one["event"], one["level"]) for one in written] == [("process.crashed", "error")]


@pytest.mark.asyncio
async def test_an_exception_escaping_a_background_task_reaches_the_sink(log_chain):
    await catch_loop_exceptions()
    asyncio.get_running_loop().call_exception_handler(
        {"message": "Task exception was never retrieved", "exception": ValueError("nobody awaited")}
    )
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.task_crashed", "error")]


class _DiesBadly:
    """Collected deterministically on ``del``."""

    def __del__(self) -> None:
        raise ValueError("dying badly")


def test_an_exception_in_a_destructor_reaches_the_sink(log_chain):
    doomed = _DiesBadly()
    del doomed
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.unraisable", "error")]


def test_a_warning_raised_by_python_itself_reaches_the_sink(log_chain):
    """A UserWarning: pytest raises on a DeprecationWarning."""
    warnings.warn("this call is going away", UserWarning, stacklevel=1)
    lines = log_chain()
    assert [(line.logger, line.level) for line in lines] == [("py.warnings", "warning")]


@pytest.mark.asyncio
async def test_a_loop_complaint_with_no_exception_is_a_warning_not_a_crash(log_chain):
    """ "Task was destroyed but it is pending!" at shutdown never raised."""
    await catch_loop_exceptions()
    asyncio.get_running_loop().call_exception_handler(
        {"message": "Task was destroyed but it is pending!"}
    )
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.loop_error", "warning")]
