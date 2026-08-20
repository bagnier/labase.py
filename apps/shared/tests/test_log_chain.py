"""The one chain every line enters the log sink through — ours and the libraries'.

structlog and stdlib ``logging`` were two unconnected outputs: a library's log reached
stdout and nothing else, and the logger name was thrown away by the print factory. These
tests hold the seam at :func:`setup_logging` — what a caller logs is what the sink
reads back — and cover the four places an exception used to escape it entirely.
"""

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
    """Third-party stdlib records used to land on stdout only, invisible to the timeline."""
    logging.getLogger("httpx").warning("connection pool exhausted")
    lines = log_chain()
    assert [(line.logger, line.name, line.level) for line in lines] == [
        ("httpx", "connection pool exhausted", "warning")
    ]


def test_only_a_library_line_is_held_to_the_warning_floor(log_chain):
    """Libraries join the chain for their degradations and bugs, not for their chatter —
    while our own level stays the one an admin tunes from the console (DEBUG under .env.test)."""
    logging.getLogger("httpx").info("connection pool refreshed")
    structlog.get_logger("apps.todo.infra.router").info("todo.created")
    lines = log_chain()
    assert [line.logger for line in lines] == ["apps.todo.infra.router"]


def _raise_in_place() -> None:
    raise ValueError("nobody is awaiting me")


def test_an_exception_escaping_a_thread_reaches_the_sink(log_chain):
    """A thread that dies used to write its traceback to stderr and nowhere else."""
    thread = threading.Thread(target=_raise_in_place, name="worker-7")
    thread.start()
    thread.join()
    lines = log_chain()
    assert [(line.logger, line.name, line.level) for line in lines] == [
        ("apps.shared.logs.chain", "process.thread_crashed", "error")
    ]


def test_a_crash_on_the_way_out_is_on_disk_before_the_process_dies(log_chain):
    """Nothing will drain the queue after this line, and nothing can: the hook runs during
    interpreter shutdown, where there is no loop left to reach the store on. The day file is the
    one sink still available, which is why it survived the move to Postgres."""
    sys.excepthook(ValueError, ValueError("the process gives up"), None)

    written = [
        json.loads(raw)
        for path in fallback_dir().glob("firehose-*.jsonl")
        for raw in path.read_text(encoding="utf-8").splitlines()
    ]

    assert [(one["event"], one["level"]) for one in written] == [("process.crashed", "error")]


@pytest.mark.asyncio
async def test_an_exception_escaping_a_background_task_reaches_the_sink(log_chain):
    """asyncio hands an unretrieved task exception to the loop's handler, which used to
    forward it to the stdlib ``asyncio`` logger — outside the chain."""
    await catch_loop_exceptions()
    asyncio.get_running_loop().call_exception_handler(
        {"message": "Task exception was never retrieved", "exception": ValueError("nobody awaited")}
    )
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.task_crashed", "error")]


class _DiesBadly:
    """A destructor that raises — CPython refcounting collects it on ``del``, deterministically."""

    def __del__(self) -> None:
        raise ValueError("dying badly")


def test_an_exception_in_a_destructor_reaches_the_sink(log_chain):
    """Python cannot propagate out of ``__del__``: it calls ``sys.unraisablehook`` instead,
    whose default writes to stderr and nowhere else."""
    doomed = _DiesBadly()
    del doomed
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.unraisable", "error")]


def test_a_warning_raised_by_python_itself_reaches_the_sink(log_chain):
    """``warnings.warn`` has its own channel, straight to stderr — a deprecation the base is
    walking into is exactly the kind of degradation the timeline is for. UserWarning and not
    DeprecationWarning because pytest is configured to raise on the latter."""
    warnings.warn("this call is going away", UserWarning, stacklevel=1)
    lines = log_chain()
    assert [(line.logger, line.level) for line in lines] == [("py.warnings", "warning")]


@pytest.mark.asyncio
async def test_a_loop_complaint_with_no_exception_is_a_warning_not_a_crash(log_chain):
    """asyncio also calls its handler for things that never raised — "Task was destroyed but it
    is pending!" at shutdown. Degraded, not a bug: it must not read as a crash."""
    await catch_loop_exceptions()
    asyncio.get_running_loop().call_exception_handler(
        {"message": "Task was destroyed but it is pending!"}
    )
    lines = log_chain()
    assert [(line.name, line.level) for line in lines] == [("process.loop_error", "warning")]
