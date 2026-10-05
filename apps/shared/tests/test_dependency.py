"""The dependency verdict (AGENTS: a broken dependency is a bug, a refusal is not)."""

from types import SimpleNamespace

import pytest
import structlog

from apps.shared.logs import capture
from apps.shared.logs.dependency import is_refusal, log_dependency_failure

_CALLER = "apps.auth.infra.router"


class _Answered(Exception):
    """Like gotrue's ``AuthApiError``."""

    def __init__(self, status: int) -> None:
        super().__init__(f"the dependency answered {status}")
        self.status = status


class _AnsweredOnItsResponse(Exception):
    """Like ``httpx.HTTPStatusError``."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"the dependency answered {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


class _AnsweredInText(Exception):
    """Like storage3's ``StorageApiError``, whose ``statusCode`` is text."""

    def __init__(self, status: str) -> None:
        super().__init__(f"the dependency answered {status}")
        self.status = status


class _PostgresAnswered(Exception):
    """Like asyncpg's error classes."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"the server answered {sqlstate}")
        self.sqlstate = sqlstate


class _PostgresAnsweredThroughSqlalchemy(Exception):
    """Like SQLAlchemy's ``DBAPIError``."""

    def __init__(self, sqlstate: str) -> None:
        super().__init__(f"the server answered {sqlstate}")
        self.orig = _PostgresAnswered(sqlstate)


class _PostgresUnreachable(Exception):
    """A ``DBAPIError`` wrapping a connection failure: no ``sqlstate``."""

    def __init__(self) -> None:
        super().__init__("connection refused")
        self.orig = ConnectionRefusedError("connection refused")


@pytest.fixture(autouse=True)
def _empty_capture_queue():
    capture._QUEUE.clear()
    yield
    capture._QUEUE.clear()


@pytest.mark.parametrize(
    "exc",
    [
        _Answered(400),
        _Answered(429),
        _AnsweredOnItsResponse(404),
        _AnsweredInText("404"),
    ],
)
def test_a_dependency_that_answers_4xx_is_refusing(exc):
    assert is_refusal(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        _Answered(500),
        _AnsweredOnItsResponse(503),
        _AnsweredInText("503"),
        _AnsweredInText("not a status at all"),
        ConnectionError("no route to host"),
        ValueError("our own mistake, on the way to calling it"),
        _PostgresUnreachable(),
        _PostgresAnswered("08006"),  # connection_failure
        _PostgresAnswered("53300"),  # too_many_connections
        _PostgresAnswered("57P03"),  # cannot_connect_now
        _PostgresAnswered("58030"),  # io_error
        _PostgresAnswered("XX000"),  # internal_error
        # Every SQL the verdict sees is ours (the settings store, the rate-limit store): an answer
        # naming our own schema or statement wrong is our bug, and read as a refusal it would leave
        # the limiter failing open with no issue.
        _PostgresAnswered("42P01"),  # undefined_table
        _PostgresAnswered("42703"),  # undefined_column
        _PostgresAnswered("42601"),  # syntax_error
        _PostgresAnswered("42501"),  # insufficient_privilege
        _PostgresAnsweredThroughSqlalchemy("42P01"),
    ],
)
def test_anything_else_is_the_dependency_breaking(exc):
    assert is_refusal(exc) is False


def test_a_refusal_is_recorded_without_opening_an_issue(log_chain):
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", _Answered(400), token="ab")

    assert [(line.name, line.level, line.payload.get("token")) for line in log_chain()] == [
        ("auth.confirm_failed", "info", "ab")
    ]
    assert list(capture._QUEUE) == []


def test_a_breakage_is_recorded_as_an_issue(log_chain):
    broken = _Answered(503)
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", broken)

    assert [(line.name, line.level) for line in log_chain()] == [("auth.confirm_failed", "error")]
    assert [captured.exc for captured in capture._QUEUE] == [broken]


def test_the_line_is_filed_under_the_caller_not_under_shared(log_chain):
    """The Timeline reads a line's app off its logger."""
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", _Answered(500))

    assert [line.logger for line in log_chain()] == [_CALLER]
