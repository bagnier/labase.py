"""One verdict for "the call outside this process failed": did it refuse, or is it broken.

The base had three answers to the same situation. Auth wrote the 4xx-or-not predicate twice
(``_log_gotrue_failure``, ``_report_refresh_failure``), and the settings store decided the
opposite — a database it could not reach was logged and left untracked. Whichever module a failing
provider was reached through then decided whether an admin ever heard about the outage.

The rule these pin: a dependency that *answers* — a 4xx — said no, and saying no is a normal
outcome. A dependency that is *broken* — unreachable, a 5xx, a client library raising something
of its own — is a bug, and the capture seam turns it into an issue.
"""

from types import SimpleNamespace

import pytest
import structlog

from apps.shared.logs import capture
from apps.shared.logs.dependency import is_refusal, log_dependency_failure

_CALLER = "apps.auth.infra.router"


class _Answered(Exception):
    """A client that hangs the status off the exception — gotrue's ``AuthApiError``."""

    def __init__(self, status: int) -> None:
        super().__init__(f"the dependency answered {status}")
        self.status = status


class _AnsweredOnItsResponse(Exception):
    """A client that hangs it off the response it wrapped — ``httpx.HTTPStatusError``."""

    def __init__(self, status_code: int) -> None:
        super().__init__(f"the dependency answered {status_code}")
        self.response = SimpleNamespace(status_code=status_code)


class _AnsweredInText(Exception):
    """A client that keeps the status as the *string* its dependency sent — storage3, which
    builds ``StorageApiError`` straight from Supabase Storage's JSON body, where ``statusCode``
    is text. Read as "never answered", every ordinary 404 from Storage becomes a bug."""

    def __init__(self, status: str) -> None:
        super().__init__(f"the dependency answered {status}")
        self.status = status


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
        _AnsweredInText("404"),  # a status is what it says, not what type it arrived as
    ],
)
def test_a_dependency_that_answers_4xx_is_refusing(exc):
    assert is_refusal(exc) is True


@pytest.mark.parametrize(
    "exc",
    [
        _Answered(500),  # the dependency broke while answering
        _AnsweredOnItsResponse(503),
        _AnsweredInText("503"),
        _AnsweredInText("not a status at all"),  # unparseable is not an answer
        ConnectionError("no route to host"),  # it never answered at all
        ValueError("our own mistake, on the way to calling it"),
    ],
)
def test_anything_else_is_the_dependency_breaking(exc):
    assert is_refusal(exc) is False


def test_a_refusal_is_recorded_without_opening_an_issue(log_chain):
    """A wrong password, an expired link, a rate limit: the dependency did its job."""
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", _Answered(400), token="ab")

    assert [(line.name, line.level, line.payload.get("token")) for line in log_chain()] == [
        ("auth.confirm_failed", "info", "ab")
    ]
    assert list(capture._QUEUE) == []


def test_a_breakage_is_recorded_as_an_issue(log_chain):
    """``exc_info`` is passed explicitly rather than resolved from the frame: the seam then holds
    wherever the helper is called from, not only from inside a live ``except`` block."""
    broken = _Answered(503)
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", broken)

    assert [(line.name, line.level) for line in log_chain()] == [("auth.confirm_failed", "error")]
    assert [captured.exc for captured in capture._QUEUE] == [broken]


def test_the_line_is_filed_under_the_caller_not_under_shared(log_chain):
    """Why the helper takes a logger instead of holding one: the timeline reads a line's app off
    the logger that wrote it, so a failure reached through here must still read as auth's."""
    log = structlog.get_logger(_CALLER)

    log_dependency_failure(log, "auth.confirm_failed", _Answered(500))

    assert [line.logger for line in log_chain()] == [_CALLER]
